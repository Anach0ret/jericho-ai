"""Подставные объекты тестов модуля «задачи»."""

from datetime import datetime, timedelta, timezone

from jericho.core.agent.entities import AgentReply

START = datetime(2026, 10, 21, 20, 0, tzinfo=timezone(timedelta(hours=2)))


class Clock:
    def __init__(self, now: datetime = START) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


class Delivered:
    def __init__(self) -> None:
        self.replies: list[tuple[str, AgentReply]] = []

    def deliver(self, task: str, reply: AgentReply) -> None:
        self.replies.append((task, reply))


class FakeRelaunch:
    def __init__(self, attended: bool, code: int = 0) -> None:
        self.attended = attended
        self.launched: list[tuple[str, ...]] = []
        self._code = code

    def unattended(self, *arguments: str) -> int:
        self.launched.append(arguments)
        return self._code


class TakenLock:
    """Замок, который держит другой процесс."""

    def acquire(self) -> bool:
        return False

    def release(self) -> None:
        raise AssertionError("замок не брали — отпускать нечего")
