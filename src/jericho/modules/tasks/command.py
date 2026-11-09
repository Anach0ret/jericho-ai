"""Команда терминала «задача» — её вызывает таймер машины."""

from __future__ import annotations

import argparse
import logging
from collections.abc import Mapping
from typing import TYPE_CHECKING

from jericho.core.services.output import Output
from jericho.core.services.relaunch import Relaunch, relaunched
from jericho.modules.tasks.entities import DeferredState
from jericho.modules.tasks.queue import DeferredQueue
from jericho.modules.tasks.settings import ScheduledCommand, ScheduledTask
from jericho.modules.tasks.timers import CronTable, SystemdUserTimers, TimersError, planned

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from jericho.core.agent.handle_phrase import HandlePhrase


class TaskCommand:
    """Выполняет задачу из настроек всегда без человека рядом, откуда бы её ни запустили.

    Запущенная из терминала, команда запускает себя ещё раз с отметкой «рядом никого нет» — подтверждения
    и разговор собираются по этой отметке. Неудача задачи — ненулевой код завершения: таймер её заметит.
    """

    name = "task"
    help = "выполнить задачу из настроек без человека рядом — так её запускает таймер"

    def __init__(
        self,
        tasks: Mapping[str, ScheduledTask],
        handle_phrase: HandlePhrase,
        outputs: Mapping[str, Output],
        relaunch: Relaunch,
    ) -> None:
        self._tasks = dict(tasks)
        self._handle_phrase = handle_phrase
        self._outputs = dict(outputs)
        self._relaunch = relaunch

    def configure(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("task", choices=sorted(self._tasks), help="имя задачи из раздела настроек `tasks`")

    def run(self, args: argparse.Namespace) -> None:
        if relaunched(self._relaunch, self.name, args.task):
            return
        task = self._tasks[args.task]
        reply = self._handle_phrase.execute(task.text)
        self._outputs[args.task].deliver(task.text, reply)
        if DeferredState.after(reply.status).run_failed:      # отказ — тоже неуспех: планировщик должен его видеть
            raise SystemExit(1)


class TimersCommand:
    """Расписание из настроек → таймеры. После правки раздела `tasks` запускают `install` ещё раз."""

    name = "timers"
    help = (
        "расписание задач: install / remove / list — таймеры systemd; crontab — файл для supercronic в контейнере"
    )

    def __init__(
        self,
        tasks: Mapping[str, ScheduledTask],
        due_check: tuple[str, ...] | None,
        timers: SystemdUserTimers,
        cron: CronTable,
        scheduler: str = "systemd",
        commands: Mapping[str, ScheduledCommand] | None = None,
    ) -> None:
        self._tasks = dict(tasks)
        self._commands = dict(commands or {})
        self._due_check = due_check
        self._timers = timers
        self._cron = cron
        self._scheduler = scheduler

    def configure(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("action", choices=("install", "remove", "list", "crontab"))

    def run(self, args: argparse.Namespace) -> None:
        if (args.action == "crontab") != (self._scheduler == "cron"):
            hint = "timers crontab — для scheduler = cron" if args.action == "crontab" else "в контейнере systemd нет: собери файл командой timers crontab"
            raise SystemExit(f"Таймеры: в разделе tasks scheduler = {self._scheduler}; {hint}")
        if args.action == "crontab":
            print(self._cron.render(planned(self._tasks, self._due_check, CronTable.TICK, self._commands)), end="")
            return
        try:
            match args.action:
                case "install":
                    change = self._timers.install(planned(self._tasks, self._due_check, SystemdUserTimers.TICK, self._commands))
                    print(f"Поставлены: {', '.join(change.installed) or 'ни одного — у задач нет schedule'}")
                    if change.removed:
                        print(f"Сняты (задачи больше нет, у неё нет schedule или выключены отложенные): {', '.join(change.removed)}")
                case "remove":
                    print(f"Сняты: {', '.join(self._timers.remove()) or 'ни одного'}")
                case _:
                    print(self._timers.show())
        except TimersError as error:
            raise SystemExit(f"Таймеры: {error}") from error


class DeferredCommand:
    """Отложенные поручения для человека и для окна на панели: список ждущих и отмена по id."""

    name = "scheduled"
    help = "отложенные поручения: без аргументов — ждущие; --cancel ID — снять одно (человек снимает сам, без «да»)"

    def __init__(self, queue: DeferredQueue) -> None:
        self._queue = queue

    def configure(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--cancel", metavar="ID", help="id ждущего поручения — из списка")

    def run(self, args: argparse.Namespace) -> None:
        if args.cancel:
            cancelled = self._queue.cancel([args.cancel])
            if not cancelled:
                raise SystemExit(f"среди ждущих нет поручения {args.cancel}")
            logger.info("deferred_cancelled", extra={"data": {"id": args.cancel, "text": cancelled[0].text, "by": "command"}})
            print(f"Снято: {cancelled[0].text}")
            return
        for item in self._queue.pending():
            print(f"{item.id}  {item.at:%d.%m.%Y %H:%M}  {item.kind.value:<6} {item.text}")
