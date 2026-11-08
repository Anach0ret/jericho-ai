import argparse
from datetime import timedelta

import pytest

from jericho.core.agent.entities import ReplyStatus
from jericho.core.agent.handle_phrase import HandlePhrase
from jericho.core.services.adapters.memory_list import MemoryList
from jericho.core.services.lock import ExclusiveLock, Unlocked
from jericho.core.testing import FakeBackend, builder
from jericho.modules.tasks.due import DueCommand
from jericho.modules.tasks.entities import Deferred, DeferredKind, DeferredState
from jericho.modules.tasks.queue import DeferredQueue
from jericho.modules.tasks.settings import DeferredSettings
from jericho.modules.tasks.tests.fakes import START, Clock, Delivered, FakeRelaunch, TakenLock

NOTHING = argparse.Namespace()


class Due:
    """Команда `due` вокруг одной очереди: что исполнено, что доставлено, что спрошено у модели."""

    def __init__(
        self,
        backend: FakeBackend | None = None,
        attended: bool = False,
        phrase_lock: ExclusiveLock | None = None,
        runs: ExclusiveLock | None = None,
    ) -> None:
        self.clock = Clock()
        self.queue = DeferredQueue(MemoryList[Deferred](), Unlocked(), self.clock)
        self.backend = backend or FakeBackend({"status": "done", "message": "сводка готова"})
        self.output = Delivered()
        self.relaunch = FakeRelaunch(attended)
        handle_phrase = HandlePhrase(builder(), self.backend, lock=phrase_lock, attended=attended)
        self.command = DueCommand(
            self.queue, handle_phrase, self.output, self.relaunch, runs or Unlocked(), DeferredSettings(enabled=True), self.clock
        )

    def at(self, kind: DeferredKind, text: str, later: timedelta) -> None:
        self.queue.add(kind, text, START + later)

    def run_after(self, passed: timedelta) -> None:
        self.clock.now = START + passed
        self.command.run(NOTHING)

    def states(self) -> list[DeferredState]:
        return [item.state for item in self.queue.items()]


class TestDueCommand:
    def test_nothing_due_touches_neither_the_model_nor_the_relaunch(self) -> None:
        due = Due(attended=True)
        due.at(DeferredKind.DO, "сводка", timedelta(hours=1))

        due.run_after(timedelta(minutes=10))

        assert due.relaunch.launched == [] and due.backend.asked == []

    def test_from_the_terminal_due_runs_again_without_a_person(self) -> None:
        due = Due(attended=True)
        due.at(DeferredKind.DO, "сводка", timedelta(0))

        due.run_after(timedelta(minutes=1))

        assert due.relaunch.launched == [("due",)]
        assert due.backend.asked == []

    def test_reminder_is_delivered_without_the_model(self) -> None:
        due = Due()
        due.at(DeferredKind.REMIND, "выключить духовку", timedelta(minutes=30))

        due.run_after(timedelta(minutes=30))

        [(_, reply)] = due.output.replies
        assert reply.message == "Напоминание: выключить духовку"
        assert due.backend.asked == [] and due.states() == [DeferredState.DONE]

    def test_late_reminder_says_how_late(self) -> None:
        due = Due()
        due.at(DeferredKind.REMIND, "созвон", timedelta(0))

        due.run_after(timedelta(hours=3, minutes=5))

        assert due.output.replies[0][1].message == "Напоминание: созвон (опоздало на 3 ч 5 мин)"

    def test_task_runs_without_a_person_and_the_reply_goes_to_the_output(self) -> None:
        due = Due()
        due.at(DeferredKind.DO, "собери сводку по почте", timedelta(hours=13))

        due.run_after(timedelta(hours=13))

        [(_, phrase)] = due.backend.asked
        assert phrase.startswith("собери сводку по почте") and HandlePhrase.UNATTENDED_NOTE in phrase
        assert due.output.replies[0][1].message == "сводка готова"
        assert due.states() == [DeferredState.DONE]

    def test_task_late_beyond_grace_is_missed_not_run(self) -> None:
        due = Due()
        due.at(DeferredKind.DO, "сводка на утро", timedelta(0))

        due.run_after(timedelta(hours=3))

        assert due.backend.asked == []
        assert due.output.replies[0][1].status is ReplyStatus.REFUSED
        assert due.states() == [DeferredState.MISSED]

    def test_failed_task_fails_the_command_and_is_not_retried(self) -> None:
        due = Due(FakeBackend(error="сеть"))
        due.at(DeferredKind.DO, "сводка", timedelta(0))

        with pytest.raises(SystemExit):
            due.run_after(timedelta(minutes=1))

        assert due.states() == [DeferredState.FAILED]
        due.run_after(timedelta(minutes=2))
        assert len(due.backend.asked) == 1      # спрошена один раз — на следующем тике повтора нет

    @pytest.mark.parametrize("status", ["refused", "clarify"])
    def test_refusal_is_not_done_and_fails_the_command(self, status: str) -> None:
        """Отказ записывался выполненным, код выхода — 0 (ревью 02.11.2026, П3a №9)."""
        due = Due(FakeBackend({"status": status, "message": "действие запрещено"}))
        due.at(DeferredKind.DO, "отправь отчёт", timedelta(0))

        with pytest.raises(SystemExit):
            due.run_after(timedelta(minutes=1))

        assert due.states() == [DeferredState.REFUSED]

    def test_busy_assistant_puts_the_task_back_and_stops_until_the_next_tick(self) -> None:
        due = Due(phrase_lock=TakenLock())
        due.at(DeferredKind.DO, "сводка", timedelta(0))
        due.at(DeferredKind.DO, "отчёт", timedelta(minutes=1))

        due.run_after(timedelta(minutes=2))

        assert due.states() == [DeferredState.PENDING, DeferredState.PENDING]
        assert due.output.replies == []

    def test_while_a_previous_run_is_busy_the_tick_leaves_everything_to_it(self) -> None:
        due = Due(runs=TakenLock())
        due.at(DeferredKind.DO, "сводка", timedelta(0))

        due.run_after(timedelta(minutes=1))

        assert due.states() == [DeferredState.PENDING] and due.backend.asked == []

    def test_running_left_by_a_crashed_run_is_reported_as_failed_not_repeated(self) -> None:
        due = Due()
        due.at(DeferredKind.DO, "отправь отчёт", timedelta(0))
        due.clock.now = START + timedelta(minutes=1)
        assert due.queue.take_next() is not None      # прошлый запуск взял поручение и упал — его код уже был ненулевым

        due.run_after(timedelta(minutes=2))

        assert due.states() == [DeferredState.FAILED] and due.backend.asked == []
        assert due.output.replies[0][1].message.startswith("Не выполнил «отправь отчёт»: исполнение прервалось")
