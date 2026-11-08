import contextlib
import logging
import os
import signal
import subprocess
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import ClassVar

import pytest

from jericho.core.services.process_tree import ProcessTree
from jericho.core.services.runner import CommandError, DryRunRunner, SubprocessRunner
from jericho.core.tools.deadline import Deadline, ToolTimeout


class Recorder:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []

    def run(self, command: Sequence[str], stdin: str | None = None, *, reads: bool = False, dry_answer: str = "") -> str:
        self.commands.append(list(command))
        return "настоящий ответ"

    def launch(self, command: Sequence[str]) -> None:
        self.run(command)


class TestDryRunRunner:
    def test_reading_command_is_executed(self) -> None:
        real = Recorder()

        assert DryRunRunner(real).run(["hyprctl", "clients", "-j"], reads=True) == "настоящий ответ"
        assert real.commands == [["hyprctl", "clients", "-j"]]

    def test_changing_command_is_only_written_to_the_journal(self, caplog: pytest.LogCaptureFixture) -> None:
        real = Recorder()

        with caplog.at_level(logging.INFO, logger="jericho"):
            answer = DryRunRunner(real).run(["hyprctl", "dispatch", "closewindow", "address:0xa"], dry_answer="ok")

        assert answer == "ok" and real.commands == []
        record = caplog.records[-1]
        assert record.getMessage() == "dry_run"
        assert record.data == {"command": ["hyprctl", "dispatch", "closewindow", "address:0xa"]}  # pyright: ignore[reportAttributeAccessIssue]

    def test_unmarked_command_is_treated_as_changing(self) -> None:
        real = Recorder()

        DryRunRunner(real).run(["rm", "-rf", "/tmp/x"])

        assert real.commands == []

    def test_launch_is_only_written_to_the_journal(self, caplog: pytest.LogCaptureFixture) -> None:
        real = Recorder()

        with caplog.at_level(logging.INFO, logger="jericho"):
            DryRunRunner(real).launch(["gio", "open", "https://example.com"])

        assert real.commands == [] and caplog.records[-1].getMessage() == "dry_run"


class TestLaunch:
    def test_does_not_wait_for_a_program_that_keeps_running(self) -> None:
        started = time.monotonic()

        SubprocessRunner(settle=0.2).launch(["sleep", "3"])

        assert time.monotonic() - started < 1.5

    def test_program_that_fails_at_once_is_an_error(self) -> None:
        with pytest.raises(CommandError, match="exit code 1"):
            SubprocessRunner(settle=2).launch(["false"])

    def test_missing_program_is_an_error(self) -> None:
        with pytest.raises(CommandError):
            SubprocessRunner().launch(["/usr/bin/no-such-program-xyz"])

    def test_program_that_finishes_well_at_once_is_fine(self) -> None:
        SubprocessRunner(settle=2).launch(["true"])


class TestRun:
    def test_failed_program_keeps_its_whole_output(self) -> None:
        """Сообщение обрезано, а вывод целиком — у ошибки: `claude` пишет причину в конце длинного JSON."""
        long = "x" * 500 + "причина"

        with pytest.raises(CommandError) as raised:
            SubprocessRunner().run(["sh", "-c", f"echo {long}; exit 1"])

        assert raised.value.output == long and len(str(raised.value)) < 400


class TestDescendants:
    """Сводка ревью 02.11.2026, №10: по сроку останавливался только прямой потомок — внук продолжал действовать.
    Критика плана 07.11.2026: срок ручки (`ToolTimeout`) и Ctrl+C — тоже прерывания, после них потомков не остаётся."""

    @pytest.fixture(autouse=True)
    def short_grace(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(ProcessTree, "GRACE", 0.2)      # внук TERM не слушает: ждать полные 2 с незачем

    @staticmethod
    def grandchild(pidfile: Path) -> list[str]:
        """`sh` запускает внука, который не слушает TERM, и ждёт его; номер внука — в файле."""
        return ["sh", "-c", f"(trap '' TERM; exec sleep 30) & echo $! > {pidfile}; wait"]

    @staticmethod
    def alive(pid: int) -> bool:
        """Жив и не зомби: зомби уже ничего не делает, его просто не успели убрать."""
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            try:
                state = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").rsplit(")", 1)[1].split()[0]
            except FileNotFoundError:
                return False
            if state == "Z":
                return False
            time.sleep(0.05)
        return True

    @staticmethod
    def pid(pidfile: Path) -> int:
        deadline = time.monotonic() + 3
        while not (pidfile.exists() and pidfile.read_text(encoding="utf-8").strip()) and time.monotonic() < deadline:
            time.sleep(0.02)
        return int(pidfile.read_text(encoding="utf-8"))

    def test_timeout_stops_the_grandchild_too(self, tmp_path: Path) -> None:
        pidfile = tmp_path / "pid"

        with pytest.raises(CommandError, match="no answer"):
            SubprocessRunner(timeout=0.5).run(self.grandchild(pidfile), reads=True)

        assert not self.alive(self.pid(pidfile))

    @pytest.mark.parametrize("interruption", [ToolTimeout, KeyboardInterrupt])
    def test_any_interruption_stops_the_group_and_goes_on(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, interruption: type[BaseException]
    ) -> None:
        pidfile, seen = tmp_path / "pid", []

        def interrupted(process: subprocess.Popen[str], *_: object, **__: object) -> tuple[str, str]:
            seen.append(self.pid(pidfile))       # внук уже запущен — тогда и прерываем, как сигнал срока посреди ожидания
            raise interruption

        monkeypatch.setattr(subprocess.Popen, "communicate", interrupted)
        with pytest.raises(interruption):
            SubprocessRunner(timeout=30).run(self.grandchild(pidfile), reads=True)

        assert not self.alive(seen[0])


class TestProcessTree:
    """Ревью 07.11.2026: вложенный запуск со своей группой (№2) и срок ручки посреди паузы TERM → KILL (№3)."""

    @pytest.fixture(autouse=True)
    def short_grace(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(ProcessTree, "GRACE", 0.5)

    def test_stopping_the_answer_stops_what_its_runner_started(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Ответ inbox → `SubprocessRunner` → программа: у программы своя группа, а остановка ответа достаёт и её."""
        pidfile = tmp_path / "pid"
        script = (
            "from jericho.core.services.runner import SubprocessRunner; "
            f"SubprocessRunner(timeout=60).run({TestDescendants.grandchild(pidfile)!r}, reads=True)"
        )
        answer = subprocess.Popen([sys.executable, "-c", script], start_new_session=True, text=True, encoding="utf-8")
        grandchild = TestDescendants.pid(pidfile)
        assert os.getpgid(grandchild) != os.getpgid(answer.pid)

        ProcessTree.stop(answer)

        assert not TestDescendants.alive(grandchild)

    def test_tool_deadline_inside_the_pause_still_kills(self, tmp_path: Path) -> None:
        """Срок runner (0,05 с) раньше срока ручки (0,15 с): `ToolTimeout` приходит посреди паузы после TERM."""
        pidfile = tmp_path / "pid"

        with pytest.raises(ToolTimeout), Deadline(0.15).limit():
            SubprocessRunner(timeout=0.05).run(TestDescendants.grandchild(pidfile), reads=True)

        assert not TestDescendants.alive(TestDescendants.pid(pidfile))


class TestLaunchedStaysAlive:
    """Ревью 07.11.2026, повтор прохода 6, №13: остановка дерева убивала и намеренно отделённое (`launch`) —
    браузер, приложение, фоновый план. Синхронное (`run`) останавливается, отделённое — живёт дальше."""

    # Ревью 0.64.3 (повтор): метка в окружении терялась у программы, очистившей окружение (`env -i`) или закрывшей
    # его чтение (`PR_SET_DUMPABLE`, как песочницы браузеров), — и отделённое снова останавливалось.
    LAUNCHED: ClassVar[dict[str, str]] = {
        "plain": "['sh', '-c', 'echo $$ > {file}; exec sleep 30']",
        "empty_environment": "['env', '-i', 'sh', '-c', 'echo $$ > {file}; exec sleep 30']",
        "unreadable_environment": (
            "[sys.executable, '-c', \"import ctypes, os, time; ctypes.CDLL(None).prctl(4, 0, 0, 0, 0); "
            "open('{file}', 'w').write(str(os.getpid())); time.sleep(30)\"]"
        ),
    }

    @pytest.mark.parametrize("program", sorted(LAUNCHED))
    def test_stopping_the_parent_spares_what_it_launched(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, program: str) -> None:
        monkeypatch.setattr(ProcessTree, "GRACE", 0.5)
        launched_file, run_file = tmp_path / "launched", tmp_path / "run"
        script = (
            "import sys; from jericho.core.services.runner import SubprocessRunner; "
            f"runner = SubprocessRunner(timeout=60, settle=0.1); "
            f"runner.launch({self.LAUNCHED[program].format(file=launched_file)}); "
            f"runner.run({TestDescendants.grandchild(run_file)!r}, reads=True)"
        )
        parent = subprocess.Popen([sys.executable, "-c", script], start_new_session=True, text=True, encoding="utf-8")
        launched: int | None = None
        stopped = False
        try:
            launched, synchronous = TestDescendants.pid(launched_file), TestDescendants.pid(run_file)
            ProcessTree.stop(parent)
            stopped = True

            assert not TestDescendants.alive(synchronous)
            assert TestDescendants.alive(launched)
        finally:
            if not stopped and parent.poll() is None:
                ProcessTree.stop(parent)
            if launched is not None:
                with contextlib.suppress(ProcessLookupError):
                    os.kill(launched, signal.SIGKILL)


class TestNoTerminalInput:
    """Ревью 0.64.4 (повтор 2), №14: программа `run()` — в фоновой группе сеанса с терминалом; унаследовав stdin-терминал,
    она замирала на чтении (SIGTTIN) и падала по сроку. Неинтерактивный запуск ввода терминала не получает."""

    @pytest.mark.skipif(sys.platform == "win32", reason="терминал PTY — POSIX")
    def test_program_reading_stdin_does_not_hang_under_a_terminal(self) -> None:
        # На Windows модуля нет: импорт здесь, а не в начале файла, — иначе не собрался бы весь файл.
        import pty

        pid, terminal = pty.fork()       # потомок — вожак сеанса с этим терминалом, как `ask` в консоли
        if pid == 0:
            try:
                output = SubprocessRunner(timeout=3).run([sys.executable, "-c", "import os; print(os.read(0, 1))"], reads=True)
                os.write(1, f"OK {output}\n".encode())
            except BaseException as error:
                os.write(1, f"FAIL {type(error).__name__}\n".encode())
            os._exit(0)
        os.write(terminal, b"x\n")
        seen = b""
        with contextlib.suppress(OSError):       # EIO — потомок вышел, терминал закрыт
            while chunk := os.read(terminal, 1024):
                seen += chunk
        os.waitpid(pid, 0)
        os.close(terminal)

        assert b"OK" in seen, seen
