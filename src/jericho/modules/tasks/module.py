"""Модуль ядра «задачи»: поручения, которые ассистент выполняет без человека рядом.

Два вида. Задачи из настроек: команда `<проект> task <имя>`, по расписанию её зовёт таймер машины.
Отложенные поручения («завтра в 9:00 сделай …»): их ставит модель ручкой, а в срок исполняет команда
`<проект> due`, которую раз в минуту зовёт тик. Оба расписания ставит `<проект> timers install`.
Свой планировщик не пишется: systemd уже умеет календарь, пропущенное после сна и журнал запусков.
Без человека запуск не может ни спросить, ни подтвердить: это держит служба подтверждения, а не промпт.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from jericho.core.management.base import Command
from jericho.core.modules.config import ModuleConfig, ModuleServices
from jericho.core.services.adapters.file_lock import FileLock
from jericho.core.services.adapters.memory_list import MemoryList
from jericho.core.services.output import output_for
from jericho.core.services.paths import Paths
from jericho.core.tools.tool import Tool
from jericho.modules.tasks.adapters.json_file import JsonDeferredStore
from jericho.modules.tasks.adapters.unit_files import DirectoryUnitFiles, DryRunUnitFiles
from jericho.modules.tasks.command import DeferredCommand, TaskCommand, TimersCommand
from jericho.modules.tasks.due import DueCommand
from jericho.modules.tasks.entities import Deferred, DeferredState
from jericho.modules.tasks.protocols import DeferredStore, UnitFiles
from jericho.modules.tasks.queue import DeferredQueue
from jericho.modules.tasks.settings import TasksSettings
from jericho.modules.tasks.timers import CronTable, SystemdUserTimers
from jericho.modules.tasks.tools import CancelScheduled, ListScheduled, Schedule

if TYPE_CHECKING:
    from jericho.core.agent.handle_phrase import HandlePhrase

PEEK = "jericho.modules.tasks.peek"     # дешёвая проверка очереди для тика — без сборки ассистента


class TasksModule(ModuleConfig):
    name = "tasks"

    DEFERRED = "tasks/deferred.json"     # в папке состояния: поручения живут дольше сеанса
    LOCK = "tasks/deferred.lock"
    RUNS_LOCK = "tasks/due.lock"         # запуски `due` по одному
    LOCK_WAIT = 5.0                      # секунд: запись очереди — доли секунды, дольше ждать незачем

    def ready(self, services: ModuleServices) -> None:
        self.services = services
        self.settings = services.settings.section(self.name, TasksSettings)
        self.queue = DeferredQueue(self.store(), FileLock(services.core.paths.state_dir / self.LOCK, self.LOCK_WAIT), services.core.clock.now)

    def store(self) -> DeferredStore:
        if self.services.core.dry_run:
            return MemoryList[Deferred]()
        return JsonDeferredStore(self.services.core.paths.state_dir / self.DEFERRED)

    def unit_files(self) -> UnitFiles:
        """«Вхолостую» `timers install` и `remove` не пишут и не удаляют unit-файлы — только в журнал."""
        real = DirectoryUnitFiles(SystemdUserTimers.directory(self.services.program))
        return DryRunUnitFiles(real) if self.services.core.dry_run else real

    def tools(self) -> Sequence[Tool[Any]]:
        deferred, core = self.settings.deferred, self.services.core
        if not deferred.enabled:
            return ()
        return (
            Schedule(self.queue, core.confirmation, deferred, core.clock.now),
            ListScheduled(self.queue, core.clock.now),
            CancelScheduled(self.queue, core.confirmation),
        )

    def commands(self, handle_phrase: HandlePhrase) -> Sequence[Command]:
        tasks, deferred, services = self.settings.items, self.settings.deferred, self.services
        output, project = services.settings.output, services.program.name
        commands: list[Command] = []
        if tasks:
            outputs = {name: output_for(task.output or output, project) for name, task in tasks.items()}
            commands.append(TaskCommand(tasks, handle_phrase, outputs, services.relaunch))
        if deferred.enabled:
            commands.append(DeferredCommand(self.queue))
            commands.append(DueCommand(
                self.queue, handle_phrase, output_for(deferred.output or output, project), services.relaunch,
                FileLock(services.core.paths.state_dir / self.RUNS_LOCK), deferred, services.core.clock.now,
            ))
        if tasks or deferred.enabled or self.settings.commands:
            timers = SystemdUserTimers(services.program, services.core.runner, self.unit_files())
            due_check = services.program.module(PEEK, str(services.core.paths.state_dir / self.DEFERRED)) if deferred.enabled else None
            cron = CronTable(services.program)
            commands.append(TimersCommand(tasks, due_check, timers, cron, self.settings.scheduler, self.settings.commands))
        return commands

    def status(self) -> Mapping[str, object]:
        """Что ассистент делает по расписанию — для окна на панели.

        `regular` — задачи и команды из настроек; `deferred` — ждущие отложенные поручения по сроку (окно снимает
        их по id); `history` — исполненные за `keep_days`, свежие сверху: «что он сделал утром».
        """
        settings = self.settings
        regular = [{"name": name, "kind": "task", "text": task.text, "schedule": task.schedule} for name, task in settings.items.items()]
        regular += [{"name": name, "kind": "command", "text": " ".join(command.command), "schedule": command.schedule} for name, command in settings.commands.items()]
        status: dict[str, object] = {"regular": regular} if regular else {}
        if not settings.deferred.enabled:
            return status
        items = self.queue.items()
        pending = [item for item in items if item.state is DeferredState.PENDING]
        finished = sorted((item for item in items if item.finished is not None), key=lambda item: item.finished or item.at, reverse=True)
        status["deferred"] = [{"id": item.id, "kind": item.kind.value, "text": item.text, "at": item.at.isoformat(timespec="minutes")} for item in pending]
        status["history"] = [
            {"id": item.id, "kind": item.kind.value, "text": item.text, "state": item.state.value, "outcome": item.outcome,
             "finished": (item.finished or item.at).isoformat(timespec="minutes")}
            for item in finished
        ]
        return status

    def eval_files(self, paths: Paths) -> Sequence[Path]:
        return (paths.state_dir / self.DEFERRED,)
