"""Модуль ядра «уведомления»: ответ человека на сводку или тревогу ассистента — о ней, а не о чём-то за год.

Уведомления пишет вывод в ящик (`MailboxOutput` → `SentLog` в папке состояния); модуль только читает их для того,
кто спрашивает: адресат `to` → пользователь по `notices.recipients`. Отдельно от `dialogue`: у реплик разговора срок —
минуты и папка сеанса, у уведомлений — сутки и папка состояния (переживают перезапуск); решение владельца 11.11.2026.
"""

from __future__ import annotations

from jericho.core.agent.task import TaskLayer
from jericho.core.modules.config import ModuleConfig, ModuleServices
from jericho.core.services.sent import SentLog
from jericho.modules.notices.settings import NoticesSettings
from jericho.modules.notices.task_layer import NoticeContext


class NoticesModule(ModuleConfig):
    name = "notices"

    def ready(self, services: ModuleServices) -> None:
        self._services = services
        self._settings = services.settings.section(self.name, NoticesSettings)

    def task_layer(self) -> TaskLayer:
        core, settings = self._services.core, self._settings
        mine = [to for to, user in settings.recipients.items() if core.user and user == core.user]
        return NoticeContext(SentLog.at(core.paths.state_dir), mine, core.foreign, settings.shown, settings.chars)
