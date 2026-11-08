"""Модуль ядра «входящие»: поручения приходят сообщениями транспорта (бота Telegram), ответы уходят ему же.

С транспортом ассистента связывает только папка (`core/services/mailbox.py`): в `inbox/` транспорт кладёт запросы,
из `outbox/` забирает ответы и сообщения без запроса (сводки, тревоги, напоминания — вывод `mailbox`).
Каждый запрос выполняется отдельным процессом от имени пользователя (`JERICHO_USER`): «да» подтверждает
только тот, кто спросил.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from datetime import timedelta
from typing import TYPE_CHECKING

from jericho.core.agent.wording import WORDINGS
from jericho.core.assembly.installation import Installation
from jericho.core.checks.base import Check
from jericho.core.management.base import Command
from jericho.core.modules.config import ModuleConfig, ModuleServices
from jericho.core.services.mailbox import Mailbox
from jericho.modules.inbox.adapters.process import ProcessAnswerer
from jericho.modules.inbox.checks import SubscriptionIsNotShared
from jericho.modules.inbox.command import AnswerCommand, InboxCommand
from jericho.modules.inbox.questions import QuestionWatch
from jericho.modules.inbox.reception import Reception
from jericho.modules.inbox.settings import InboxSettings

if TYPE_CHECKING:
    from jericho.core.agent.handle_phrase import HandlePhrase


class InboxModule(ModuleConfig):
    name = "inbox"

    INBOX = "inbox"
    OUTBOX = "outbox"

    def ready(self, services: ModuleServices) -> None:
        self.services = services
        self.settings = services.settings.section(self.name, InboxSettings)
        # Входящий файл здесь — фраза пользователя: файловые ручки, пишущие сюда, подделали бы его «да» (ревью 02.11.2026).
        services.core.own_paths.add(self.settings.directory)

    def checks(self) -> Sequence[Check]:
        return (SubscriptionIsNotShared(),)

    def commands(self, handle_phrase: HandlePhrase) -> Sequence[Command]:
        settings, program = self.settings, self.services.program
        inbox, outbox = Mailbox(settings.directory / self.INBOX), Mailbox(settings.directory / self.OUTBOX)
        answerer = ProcessAnswerer(
            program.command,
            {**os.environ, **program.environment},
            Installation.USER_VARIABLE,
            timeout=self.services.settings.agent.timeout + settings.answer_margin,
        )
        reception = Reception(inbox, outbox, answerer, settings.users, settings.max_text)
        questions = QuestionWatch(
            settings.users, self.services.core.paths, timedelta(minutes=self.services.settings.confirmation_minutes),
            timedelta(minutes=settings.remind_minutes) if settings.remind_minutes else None, outbox,
            wording=WORDINGS[self.services.settings.language],
        )
        return (InboxCommand(reception, settings.poll_seconds, questions), AnswerCommand(handle_phrase, outbox, self.services.core.confirmation))
