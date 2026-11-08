import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

import psutil
import pytest

from jericho.core.agent.entities import ReplyStatus
from jericho.core.agent.handle_phrase import HandlePhrase
from jericho.core.agent.task import Outcome, Task, TaskHandler
from jericho.core.services.adapters.file_lock import FileLock
from jericho.core.services.process_tree import ProcessTree
from jericho.core.services.stop import PhraseStopper, stop_tree
from jericho.core.testing import FakeBackend, builder


class Interrupted:
    """Слой, на котором поручение обрывается так же, как от `stop`."""

    def handle(self, task: Task, proceed: TaskHandler) -> Outcome:
        raise KeyboardInterrupt


class TestStop:
    def test_interrupted_phrase_is_answered_as_stopped(self) -> None:
        reply = HandlePhrase(builder(), FakeBackend({"status": "done", "message": "ок"}), [Interrupted()]).execute("открой")

        assert reply.status is ReplyStatus.STOPPED

    def test_nothing_to_stop_when_the_lock_is_free(self, tmp_path: Path) -> None:
        sent: list[tuple[int, int]] = []

        assert PhraseStopper(FileLock(tmp_path / "phrase.lock"), halt=lambda pid: sent.append((pid, 0))).stop() is None
        assert sent == []

    def test_holder_of_the_lock_gets_the_interrupt(self, tmp_path: Path) -> None:
        """Настоящий второй процесс держит замок: `stop` находит его по файлу замка и прерывает."""
        lock = tmp_path / "phrase.lock"
        holder = subprocess.Popen([sys.executable, "-c", (
            "import os, sys, time\n"
            "from pathlib import Path\n"
            "from jericho.core.services.adapters.file_lock import FileLock\n"
            f"held = FileLock(Path({str(lock)!r})); held.acquire(); print(os.getpid(), flush=True)\n"
            "try:\n    time.sleep(30)\nexcept KeyboardInterrupt:\n    sys.exit(42)\n"
        )], stdout=subprocess.PIPE, text=True, encoding="utf-8")
        assert holder.stdout is not None
        pid = int(holder.stdout.readline())      # свой номер: на Windows python.exe из venv — запускающая обёртка

        assert FileLock(lock).holder() == pid              # попытка взять занятый замок номер не стирает
        assert PhraseStopper(FileLock(lock)).stop() == pid
        # POSIX: SIGINT — прерывание, фраза выходит сама (код 42); Windows: процесс завершается сразу (security.md).
        assert holder.wait(timeout=5) == 42 if sys.platform != "win32" else holder.wait(timeout=5) != 0

    def test_process_does_not_stop_itself(self, tmp_path: Path) -> None:
        lock = FileLock(tmp_path / "phrase.lock")
        lock.acquire()
        sent: list[int] = []

        assert PhraseStopper(FileLock(tmp_path / "phrase.lock"), halt=lambda pid: sent.append(pid)).stop() is None
        assert sent == []

    @pytest.mark.parametrize("halt", [None, stop_tree], ids=["system", "windows_way"])
    def test_nothing_the_phrase_started_keeps_running(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, halt: Callable[[int], None] | None) -> None:
        """Ревью Codex 08.11.2026, №8: держатель → программа → внук; после `stop` не живёт никто — на POSIX держатель
        останавливает своё дерево сам (прерывание), на Windows дерево останавливает `stop`. Способ Windows
        (`stop_tree`) проверяется и здесь — на любой ОС."""
        monkeypatch.setattr(ProcessTree, "GRACE", 0.3)
        lock, pids = tmp_path / "phrase.lock", tmp_path / "pids"
        grandchild = (
            "import os, signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
            f"open({str(pids)!r}, 'a', encoding='utf-8').write(f'{{os.getpid()}}\\n'); time.sleep(30)"
        )
        program = f"import subprocess, sys; subprocess.Popen([sys.executable, '-c', {grandchild!r}]).wait()"
        holder = subprocess.Popen([sys.executable, "-c", (
            "import os, sys\n"
            "from pathlib import Path\n"
            "from jericho.core.services.adapters.file_lock import FileLock\n"
            "from jericho.core.services.runner import SubprocessRunner\n"
            f"held = FileLock(Path({str(lock)!r})); held.acquire()\n"
            f"open({str(pids)!r}, 'a', encoding='utf-8').write(f'{{os.getpid()}}\\n')\n"
            f"SubprocessRunner(timeout=60).run([sys.executable, '-c', {program!r}], reads=True)\n"
        )], text=True, encoding="utf-8")
        try:
            started = wait_for_lines(pids, 2)
            holder_pid, grandchild_pid = started[0], started[1]

            assert PhraseStopper(FileLock(lock), halt=halt).stop() == holder_pid
            holder.wait(timeout=10)

            assert not running(holder_pid) and not running(grandchild_pid)
        finally:
            if holder.poll() is None:
                holder.kill()


def wait_for_lines(file: Path, count: int) -> list[int]:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        lines = file.read_text(encoding="utf-8").split() if file.exists() else []
        if len(lines) >= count:
            return [int(line) for line in lines]
        time.sleep(0.05)
    raise AssertionError(f"процессы не запустились: {file}")


def running(pid: int, wait: float = 5) -> bool:
    """Жив и не зомби — спустя `wait` секунд на завершение."""
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        try:
            if psutil.Process(pid).status() == psutil.STATUS_ZOMBIE:
                return False
        except psutil.NoSuchProcess:
            return False
        time.sleep(0.05)
    return True
