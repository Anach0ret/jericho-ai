import subprocess
import sys
from pathlib import Path

from jericho.core.agent.entities import ReplyStatus
from jericho.core.agent.handle_phrase import HandlePhrase
from jericho.core.agent.task import Outcome, Task, TaskHandler
from jericho.core.services.adapters.file_lock import FileLock
from jericho.core.services.stop import PhraseStopper
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

        assert PhraseStopper(FileLock(tmp_path / "phrase.lock"), kill=lambda pid, sig: sent.append((pid, sig))).stop() is None
        assert sent == []

    def test_holder_of_the_lock_gets_the_interrupt(self, tmp_path: Path) -> None:
        """Настоящий второй процесс держит замок: `stop` находит его по файлу замка и прерывает."""
        lock = tmp_path / "phrase.lock"
        holder = subprocess.Popen([sys.executable, "-c", (
            "import sys, time\n"
            "from pathlib import Path\n"
            "from jericho.core.services.adapters.file_lock import FileLock\n"
            f"held = FileLock(Path({str(lock)!r})); held.acquire(); print('held', flush=True)\n"
            "try:\n    time.sleep(30)\nexcept KeyboardInterrupt:\n    sys.exit(42)\n"
        )], stdout=subprocess.PIPE, text=True, encoding="utf-8")
        assert holder.stdout is not None and holder.stdout.readline().strip() == "held"

        assert FileLock(lock).holder() == holder.pid              # попытка взять занятый замок номер не стирает
        assert PhraseStopper(FileLock(lock)).stop() == holder.pid
        assert holder.wait(timeout=5) == 42

    def test_process_does_not_stop_itself(self, tmp_path: Path) -> None:
        lock = FileLock(tmp_path / "phrase.lock")
        lock.acquire()
        sent: list[int] = []

        assert PhraseStopper(FileLock(tmp_path / "phrase.lock"), kill=lambda pid, sig: sent.append(sig)).stop() is None
        assert sent == []
