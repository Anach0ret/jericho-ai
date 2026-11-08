"""Расписание: пользовательские таймеры systemd или файл для supercronic, собранные из настроек.

Свой планировщик не пишем: systemd уже умеет запускать по календарю, догонять пропущенное после сна
(`Persistent=true`), держать журнал запусков и переживать перезагрузку. Модуль только переводит раздел
`tasks` в таймеры: по одному на задачу с `schedule` и тик раз в минуту для отложенных поручений.
"""

from __future__ import annotations

import shlex
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from jericho.core.assembly.installation import Installation
from jericho.core.services.program import Program
from jericho.core.services.runner import CommandError, CommandRunner
from jericho.modules.tasks.protocols import UnitFiles
from jericho.modules.tasks.settings import ScheduledCommand, ScheduledTask


class TimersError(Exception):
    """Таймеры не поставить: неверное расписание или systemd ответил ошибкой."""


@dataclass(frozen=True, slots=True)
class Timer:
    """Что запустить и когда: команда ассистента с аргументами и выражение расписания."""

    unit: str                        # имя без имени проекта: «task-morning», «due»
    arguments: tuple[str, ...]       # аргументы команды ассистента: («task», «morning»)
    schedule: str                    # календарь systemd или выражение cron — по планировщику
    description: str
    condition: tuple[str, ...] = ()  # команда-проверка: ассистент запускается, только если она вышла с 0
    environment: Mapping[str, str] = field(default_factory=dict)    # сверх переменных проекта: «рядом никого нет»


def planned(
    tasks: Mapping[str, ScheduledTask], due_check: tuple[str, ...] | None, tick: str, commands: Mapping[str, ScheduledCommand] | None = None
) -> list[Timer]:
    """Таймеры по настройкам: задачи с `schedule`, команды проекта и тик `due`, если отложенные поручения включены
    (`due_check` — дешёвая проверка «наступило ли что-нибудь», без неё тик собирал бы ассистента раз в минуту).

    Команда идёт с отметкой «рядом никого нет»: её вопрос «да» не должен ждать ответа от того, кто напишет днём.
    """
    timers = [Timer(f"task-{name}", ("task", name), task.schedule, f"задача {name}") for name, task in tasks.items() if task.schedule]
    unattended = {Installation.UNATTENDED_VARIABLE: "1"}
    timers += [
        Timer(f"command-{name}", command.command, command.schedule, f"команда {name}", environment=unattended)
        for name, command in (commands or {}).items()
    ]
    if due_check is not None:
        timers.append(Timer("due", ("due",), tick, "отложенные поручения", due_check))
    return timers


@dataclass(frozen=True, slots=True)
class TimersChange:
    installed: tuple[str, ...]
    removed: tuple[str, ...]


class SystemdUserTimers:
    """Таймеры в `~/.config/systemd/user/`. Свои файлы помечены первой строкой — чужие не трогаются.

    Файлы — через порт `UnitFiles`: «вхолостую» модуль даёт подмену, и ни запись, ни удаление до диска не доходят.
    """

    MARK = "# Создано jericho: таймер задачи. Не править руками — меняй раздел tasks и запускай timers install."
    ENVIRONMENT_FILE = "environment"      # в папке файлов машины: ключи API для задач, по строке ИМЯ=значение
    TICK = "*:*:00"                       # раз в минуту

    def __init__(self, program: Program, runner: CommandRunner, units: UnitFiles) -> None:
        self._program = program
        self._runner = runner
        self._units = units

    @staticmethod
    def directory(program: Program) -> Path:
        return program.user_config_home / "systemd" / "user"

    def install(self, timers: Sequence[Timer]) -> TimersChange:
        self._check(timers)
        self._refuse_foreign_files(timers)
        removed = self._remove(set(self._installed()) - {timer.unit for timer in timers})
        for timer in timers:
            self._units.write(self._file(timer.unit, "service"), self.service(timer))
            self._units.write(self._file(timer.unit, "timer"), self.timer(timer))
        self._systemctl("daemon-reload")
        if timers:
            self._systemctl("enable", "--now", *(self._file(timer.unit, "timer") for timer in timers))
        return TimersChange(tuple(timer.unit for timer in timers), removed)

    def remove(self) -> tuple[str, ...]:
        removed = self._remove(set(self._installed()))
        self._systemctl("daemon-reload")
        return removed

    def show(self) -> str:
        return self._systemctl("list-timers", "--all", f"{self._prefix}*.timer", reads=True)

    def service(self, timer: Timer) -> str:
        variables = {**self._program.environment, **timer.environment}
        environment = "\n".join(f"Environment={self._quote(f'{key}={value}')}" for key, value in variables.items())
        command = " ".join(self._quote(part) for part in (*self._program.command, *timer.arguments))
        condition = f"ExecCondition={' '.join(self._quote(part) for part in timer.condition)}\n" if timer.condition else ""
        return (
            f"{self.MARK}\n[Unit]\nDescription={self._program.name}: {timer.description}\n\n"
            f"[Service]\nType=oneshot\n{environment}\n"
            f"EnvironmentFile=-{self._escape(str(self._program.config_dir / self.ENVIRONMENT_FILE))}\n"
            f"{condition}ExecStart={command}\n"
        )

    def timer(self, timer: Timer) -> str:
        return (
            f"{self.MARK}\n[Unit]\nDescription={self._program.name}: расписание — {timer.description}\n\n"
            f"[Timer]\nOnCalendar={self._escape(timer.schedule)}\nPersistent=true\n\n"
            "[Install]\nWantedBy=timers.target\n"
        )

    @property
    def _prefix(self) -> str:
        return f"{self._program.name}-"

    def _file(self, unit: str, kind: str) -> str:
        return f"{self._prefix}{unit}.{kind}"

    def _installed(self) -> list[str]:
        """Таймеры, которые уже стоят: только файлы с нашей пометкой."""
        return [
            name.removeprefix(self._prefix).removesuffix(".timer")
            for name in self._units.names(f"{self._prefix}*.timer") if self._ours(name)
        ]

    def _remove(self, units: set[str]) -> tuple[str, ...]:
        if not units:
            return ()
        self._systemctl("disable", "--now", *(self._file(unit, "timer") for unit in sorted(units)))
        for unit in units:
            for kind in ("timer", "service"):
                if self._ours(name := self._file(unit, kind)):      # каждый файл пары — свой ли, а не только `.timer`
                    self._units.remove(name)
        return tuple(sorted(units))

    def _ours(self, name: str) -> bool:
        text = self._units.read(name)
        return text is not None and text.startswith(self.MARK)

    def _refuse_foreign_files(self, timers: Sequence[Timer]) -> None:
        """Файл с тем же именем, написанный не нами, не перезаписывается — до любых изменений (ревью R13)."""
        foreign = [
            name for timer in timers for kind in ("service", "timer")
            if self._units.read(name := self._file(timer.unit, kind)) is not None and not self._ours(name)
        ]
        if foreign:
            raise TimersError(f"files exist and were not written by timers install — rename the task or remove them: {', '.join(foreign)}")

    def _check(self, timers: Sequence[Timer]) -> None:
        wrong: list[str] = []
        for timer in timers:
            try:
                self._runner.run(["systemd-analyze", "calendar", timer.schedule], reads=True)
            except CommandError:
                wrong.append(f"{timer.unit}: «{timer.schedule}»")
        if wrong:
            raise TimersError(f"schedule is not a systemd calendar expression — {'; '.join(wrong)}")

    def _systemctl(self, *arguments: str, reads: bool = False) -> str:
        try:
            return self._runner.run(["systemctl", "--user", *arguments], reads=reads)
        except CommandError as error:
            raise TimersError(f"systemctl {arguments[0]}: {error}") from error

    @classmethod
    def _quote(cls, value: str) -> str:
        """Слово для строки unit-файла: в кавычках, с экранированием — пробелы и «%» не ломают разбор systemd."""
        return '"' + cls._escape(value).replace("\\", "\\\\").replace('"', '\\"') + '"'

    @staticmethod
    def _escape(value: str) -> str:
        return value.replace("%", "%%")      # «%» в unit-файле — начало подстановки


class CronTable:
    """Расписание для supercronic — cron для контейнеров: пишет в stdout, так что запуски видны в `docker logs`.

    Каждая строка запускает команду ассистента с переменными проекта через `env`: так строка не зависит от того,
    какое окружение у самого supercronic.
    """

    TICK = "* * * * *"      # раз в минуту

    def __init__(self, program: Program) -> None:
        self._program = program

    def render(self, timers: Sequence[Timer]) -> str:
        lines = [f"# {self._program.name}: расписание задач. Собрано `{self._program.name} timers crontab` — не править руками."]
        for timer in timers:
            variables = {**self._program.environment, **timer.environment}
            environment = " ".join(shlex.quote(f"{key}={value}") for key, value in variables.items())
            command = " ".join(shlex.quote(part) for part in (*self._program.command, *timer.arguments))
            condition = " ".join(shlex.quote(part) for part in timer.condition)
            run = f"env {environment} {command}"
            # Проверка — условием, а не через «&&»: «нечего делать» (код 1) — не сбой запуска, cron не пишет ошибку.
            lines.append(f"{timer.schedule} {f'if {condition}; then {run}; fi' if condition else run}")
        return "\n".join(lines) + "\n"
