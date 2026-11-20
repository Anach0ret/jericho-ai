"""Модуль ядра «фоновые работы»: что идёт и чем кончилось — строкой в промпте (`{{jobs}}`); отложенные продолжения
(`then`) — ручкой `job_continue` после «да».

Сами работы — у модулей (скачивание, расшифровка, отправка файла, прогон плана): они идут отдельным запуском и
пишут итог через `JobJournal`. Этот модуль показывает их модели, чтобы на «готово?» она не запускала дело заново.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from jericho.core.management.base import Command
from jericho.core.modules.config import ModuleConfig, ModuleServices
from jericho.core.prompting.protocols import PromptContext
from jericho.core.services.output import output_for
from jericho.core.tools.tool import Tool
from jericho.modules.jobs.command import JobsCommand
from jericho.modules.jobs.context import JobsLine
from jericho.modules.jobs.tools import ContinueJob

if TYPE_CHECKING:
    from jericho.core.agent.handle_phrase import HandlePhrase


class JobsModule(ModuleConfig):
    name = "jobs"

    def ready(self, services: ModuleServices) -> None:
        self._services = services
        self._jobs = services.background()

    def tools(self) -> Sequence[Tool[Any]]:
        services = self._services
        return (ContinueJob(self._jobs.book, services.core.user, services.core.runner, services.program),)

    def contexts(self) -> Sequence[PromptContext]:
        jobs, core = self._jobs, self._services.core
        return (JobsLine(jobs.history, jobs.book, core.user, core.clock.now, jobs.settings.shown_hours, jobs.settings.shown),)

    def commands(self, handle_phrase: HandlePhrase) -> Sequence[Command]:
        services = self._services
        run = self._jobs.continuations(output_for(services.settings.output, services.program.name), handle_phrase)
        return (JobsCommand(self._jobs.book, run, services.core.user),)
