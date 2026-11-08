import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar, cast

import pytest
from pydantic import ValidationError

from jericho.core.modules.config import ModuleServices
from jericho.core.services.program import Program
from jericho.core.services.runner import CommandError, SubprocessRunner
from jericho.modules.tasks.adapters.unit_files import DirectoryUnitFiles, DryRunUnitFiles
from jericho.modules.tasks.module import TasksModule
from jericho.modules.tasks.settings import ScheduledCommand, ScheduledTask, TasksSettings
from jericho.modules.tasks.timers import CronTable, SystemdUserTimers, Timer, TimersError, planned

needs_systemd = pytest.mark.skipif(shutil.which("systemd-analyze") is None, reason="нет systemd-analyze")


class Systemctl:
    """`systemctl` подменён: таймеры на машине не ставятся. Календарь проверяет настоящий systemd-analyze, если он есть."""

    def __init__(self, bad_schedule: str = "") -> None:
        self.calls: list[list[str]] = []
        self._bad = bad_schedule

    def run(self, command: Sequence[str], stdin: str | None = None, *, reads: bool = False, dry_answer: str = "") -> str:
        if command[0] == "systemd-analyze":
            if command[-1] == self._bad:
                raise CommandError("bad")
            return ""
        self.calls.append(list(command))
        return ""

    def launch(self, command: Sequence[str]) -> None:
        pass


def unit_dir(tmp_path: Path) -> DirectoryUnitFiles:
    return DirectoryUnitFiles(tmp_path / ".config/systemd/user")


def program(tmp_path: Path) -> Program:
    environment = {"JERICHO_SETTINGS_MODULE": "home.settings", "JERICHO_CONFIGURATION": "Live"}
    return Program("home", (sys.executable, "-m", "jericho"), environment, tmp_path / ".config/home", tmp_path / ".config")


MORNING = {"morning": ScheduledTask(text="сводка", schedule="*-*-* 08:00"), "manual": ScheduledTask(text="вручную")}


PEEK = ("/usr/bin/python3", "-m", "jericho.modules.tasks.peek", "/state/tasks/deferred.json")


def systemd(tasks: dict[str, ScheduledTask], deferred: bool = False) -> list[Timer]:
    return planned(tasks, PEEK if deferred else None, SystemdUserTimers.TICK)


class TestTimers:
    def test_only_scheduled_tasks_get_a_timer_and_it_is_enabled(self, tmp_path: Path) -> None:
        systemctl = Systemctl()

        change = SystemdUserTimers(program(tmp_path), systemctl, unit_dir(tmp_path)).install(systemd(MORNING))

        units = tmp_path / ".config/systemd/user"
        assert change.installed == ("task-morning",)
        assert sorted(path.name for path in units.iterdir()) == ["home-task-morning.service", "home-task-morning.timer"]
        assert systemctl.calls[-1] == ["systemctl", "--user", "enable", "--now", "home-task-morning.timer"]
        service = (units / "home-task-morning.service").read_text()
        assert 'Environment="JERICHO_SETTINGS_MODULE=home.settings"' in service
        assert service.rstrip().endswith(f'"{sys.executable}" "-m" "jericho" "task" "morning"')

    def test_timer_of_a_task_that_lost_its_schedule_is_removed_and_foreign_units_stay(self, tmp_path: Path) -> None:
        timers, units = SystemdUserTimers(program(tmp_path), Systemctl(), unit_dir(tmp_path)), tmp_path / ".config/systemd/user"
        timers.install(systemd(MORNING))
        (units / "home-task-mine.timer").write_text("[Timer]\n")        # написан руками — не наш

        change = timers.install(systemd({"manual": ScheduledTask(text="вручную")}))

        assert change.removed == ("task-morning",)
        assert sorted(path.name for path in units.iterdir()) == ["home-task-mine.timer"]

    def test_wrong_schedule_stops_before_anything_is_written(self, tmp_path: Path) -> None:
        systemctl = Systemctl(bad_schedule="каждое утро")

        with pytest.raises(TimersError, match="task-morning: «каждое утро»"):
            SystemdUserTimers(program(tmp_path), systemctl, unit_dir(tmp_path)).install(systemd({"morning": ScheduledTask(text="сводка", schedule="каждое утро")}))

        assert systemctl.calls == [] and not (tmp_path / ".config/systemd").exists()

    def test_deferred_tasks_get_a_tick_every_minute(self, tmp_path: Path) -> None:
        change = SystemdUserTimers(program(tmp_path), Systemctl(), unit_dir(tmp_path)).install(systemd(MORNING, deferred=True))

        units = tmp_path / ".config/systemd/user"
        assert change.installed == ("task-morning", "due")
        assert "OnCalendar=*:*:00\nPersistent=true" in (units / "home-due.timer").read_text()
        service = (units / "home-due.service").read_text()
        assert 'ExecCondition="/usr/bin/python3" "-m" "jericho.modules.tasks.peek" "/state/tasks/deferred.json"' in service
        assert service.rstrip().endswith('"jericho" "due"')

    def test_tick_is_removed_when_deferred_tasks_are_switched_off(self, tmp_path: Path) -> None:
        timers = SystemdUserTimers(program(tmp_path), Systemctl(), unit_dir(tmp_path))
        timers.install(systemd(MORNING, deferred=True))

        change = timers.install(systemd(MORNING))

        assert change.removed == ("due",)
        assert not (tmp_path / ".config/systemd/user/home-due.timer").exists()

    @needs_systemd
    def test_systemd_accepts_the_written_units(self, tmp_path: Path) -> None:
        """Настоящий systemd-analyze: календарь и файлы таймера разбираются без ошибок (только чтение)."""
        timers = SystemdUserTimers(program(tmp_path), Systemctl(), unit_dir(tmp_path))
        timers.install(systemd(MORNING, deferred=True))
        SubprocessRunner().run(["systemd-analyze", "calendar", "*-*-* 08:00"], reads=True)
        SubprocessRunner().run(["systemd-analyze", "calendar", SystemdUserTimers.TICK], reads=True)

        units = tmp_path / ".config/systemd/user"
        verified = subprocess.run(
            ["systemd-analyze", "--user", "verify", *(str(units / f"home-{unit}.{kind}") for unit in ("task-morning", "due") for kind in ("timer", "service"))],
            capture_output=True, text=True, check=False,
        )
        assert verified.returncode == 0, verified.stderr


def test_file_of_the_same_name_written_by_hand_is_not_overwritten(tmp_path: Path) -> None:
    """Ревью R13: метка проверялась только при снятии — установка молча заменяла чужой файл."""
    units = tmp_path / ".config/systemd/user"
    units.mkdir(parents=True)
    (units / "home-task-morning.service").write_text("[Service]\nExecStart=/my/own\n")
    systemctl = Systemctl()

    with pytest.raises(TimersError, match="home-task-morning.service"):
        SystemdUserTimers(program(tmp_path), systemctl, unit_dir(tmp_path)).install(systemd(MORNING))

    assert (units / "home-task-morning.service").read_text() == "[Service]\nExecStart=/my/own\n"
    assert systemctl.calls == [] and not (units / "home-task-morning.timer").exists()


class TestCron:
    """В контейнере systemd нет: расписание — файл для supercronic."""

    def test_crontab_runs_each_scheduled_task_with_the_project_environment(self, tmp_path: Path) -> None:
        tasks = {"morning": ScheduledTask(text="сводка", schedule="0 8 * * *"), "manual": ScheduledTask(text="вручную")}

        table = CronTable(program(tmp_path)).render(planned(tasks, None, CronTable.TICK))

        (line,) = [line for line in table.splitlines() if not line.startswith("#")]
        assert line.startswith("0 8 * * * env JERICHO_SETTINGS_MODULE=home.settings JERICHO_CONFIGURATION=Live ")
        assert line.endswith("-m jericho task morning")

    def test_crontab_has_the_tick_when_deferred_tasks_are_on(self, tmp_path: Path) -> None:
        table = CronTable(program(tmp_path)).render(planned({}, PEEK, CronTable.TICK))

        (line,) = [line for line in table.splitlines() if not line.startswith("#")]
        assert line.startswith("* * * * * if /usr/bin/python3 -m jericho.modules.tasks.peek /state/tasks/deferred.json; then env ")
        assert line.endswith("-m jericho due; fi")

    @pytest.mark.parametrize(("condition", "command", "code"), [("false", "true", 0), ("true", "true", 0), ("true", "false", 1)])
    def test_nothing_to_do_is_not_a_failure_but_a_failing_command_is(self, tmp_path: Path, condition: str, command: str, code: int) -> None:
        """supercronic пишет ошибку на каждый ненулевой код: «наступивших нет» раз в минуту — не сбой."""
        shell = Program("p", ("sh", "-c"), {}, tmp_path, tmp_path)
        line = CronTable(shell).render([Timer("due", (command,), "* * * * *", "тик", (condition,))]).splitlines()[1]

        assert subprocess.run(["sh", "-c", line.removeprefix("* * * * * ")], check=False).returncode == code

    @pytest.mark.parametrize("schedule", ["0 8 * * *", "30 9 * * 1-5", "*/15 * * * *", "@hourly"])
    def test_cron_expressions_are_accepted(self, schedule: str) -> None:
        TasksSettings(scheduler="cron", items={"t": ScheduledTask(text="x", schedule=schedule)})

    def test_systemd_calendar_under_cron_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="not a cron expression"):
            TasksSettings(scheduler="cron", items={"t": ScheduledTask(text="x", schedule="*-*-* 08:00")})


class TestScheduledCommands:
    """Команда проекта по расписанию — без модели и без человека рядом."""

    COMMANDS: ClassVar[dict[str, ScheduledCommand]] = {"watch": ScheduledCommand(command=("watch",), schedule="*/10 * * * *")}

    def test_command_goes_to_crontab_unattended(self, tmp_path: Path) -> None:
        table = CronTable(program(tmp_path)).render(planned({}, None, CronTable.TICK, self.COMMANDS))

        line = table.splitlines()[1]
        assert line.startswith("*/10 * * * * env ") and line.endswith(" watch")
        assert "JERICHO_UNATTENDED=1" in line

    def test_command_becomes_a_systemd_timer_unattended(self, tmp_path: Path) -> None:
        [timer] = planned({}, None, SystemdUserTimers.TICK, {"clean": ScheduledCommand(command=("clean",), schedule="daily")})

        service = SystemdUserTimers(program(tmp_path), Systemctl(), unit_dir(tmp_path)).service(timer)

        assert timer.unit == "command-clean" and 'Environment="JERICHO_UNATTENDED=1"' in service

    def test_cron_scheduler_checks_command_schedules_too(self) -> None:
        with pytest.raises(ValidationError, match="watch"):
            TasksSettings(scheduler="cron", commands={"watch": ScheduledCommand(command=("watch",), schedule="every ten minutes")})


class TestDryRun:
    """Сводка ревью 02.11.2026, №6: «вхолостую» `timers install` писал unit-файлы, хотя `systemctl` шёл в журнал.
    Критика плана 07.11.2026: удаление старого расписания — тоже изменение диска."""

    def dry(self, tmp_path: Path) -> SystemdUserTimers:
        return SystemdUserTimers(program(tmp_path), Systemctl(), DryRunUnitFiles(unit_dir(tmp_path)))

    def files(self, tmp_path: Path) -> dict[str, str]:
        folder = tmp_path / ".config/systemd/user"
        return {path.name: path.read_text() for path in sorted(folder.iterdir())} if folder.is_dir() else {}

    def test_install_writes_nothing(self, tmp_path: Path) -> None:
        change = self.dry(tmp_path).install(systemd(MORNING))

        assert change.installed == ("task-morning",) and self.files(tmp_path) == {}

    def test_replacing_and_removing_leave_the_real_timers_alone(self, tmp_path: Path) -> None:
        SystemdUserTimers(program(tmp_path), Systemctl(), unit_dir(tmp_path)).install(systemd(MORNING))
        before = self.files(tmp_path)

        replaced = self.dry(tmp_path).install([])
        removed = self.dry(tmp_path).remove()

        assert (replaced.removed, removed) == (("task-morning",), ("task-morning",))
        assert self.files(tmp_path) == before

    def test_the_module_gives_the_dry_files_in_dry_run(self, tmp_path: Path) -> None:
        module = TasksModule()
        module.services = cast(ModuleServices, SimpleNamespace(core=SimpleNamespace(dry_run=True), program=program(tmp_path)))

        assert isinstance(module.unit_files(), DryRunUnitFiles)
