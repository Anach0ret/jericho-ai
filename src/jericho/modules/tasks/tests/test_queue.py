from collections.abc import Sequence
from datetime import timedelta
from pathlib import Path

import pytest

from jericho.core.services.adapters.memory_list import MemoryList
from jericho.core.services.lock import Unlocked
from jericho.modules.tasks import peek
from jericho.modules.tasks.adapters.json_file import JsonDeferredStore
from jericho.modules.tasks.entities import Deferred, DeferredKind, DeferredState
from jericho.modules.tasks.queue import DeferredQueue, QueueBusy
from jericho.modules.tasks.tests.fakes import START, Clock, TakenLock


def queue(clock: Clock, store: JsonDeferredStore | MemoryList[Deferred] | None = None) -> DeferredQueue:
    return DeferredQueue(store or MemoryList[Deferred](), Unlocked(), clock)


class TestQueue:
    def test_added_item_waits_for_its_time(self) -> None:
        clock = Clock()
        tasks = queue(clock)
        item = tasks.add(DeferredKind.REMIND, "выключить духовку", START + timedelta(minutes=30))

        assert [entry.id for entry in tasks.pending()] == [item.id]
        assert not tasks.has_due()
        clock.now += timedelta(minutes=30)
        assert tasks.has_due()

    def test_due_items_are_handed_out_one_by_one_earliest_first_already_marked_running(self) -> None:
        clock, store = Clock(), MemoryList[Deferred]()
        tasks = queue(clock, store)
        later = tasks.add(DeferredKind.DO, "сводка по почте", START + timedelta(hours=1))
        earlier = tasks.add(DeferredKind.REMIND, "духовка", START)
        clock.now += timedelta(hours=2)

        first = tasks.take_next()

        assert first is not None and first.id == earlier.id and first.state is DeferredState.RUNNING
        assert {item.id: item.state for item in store.load()} == {later.id: DeferredState.PENDING, earlier.id: DeferredState.RUNNING}
        second = tasks.take_next()
        assert second is not None and second.id == later.id
        assert tasks.take_next() is None      # следующий тик после упавшего запуска — повтора нет

    def test_released_item_waits_again(self) -> None:
        tasks = queue(Clock())
        tasks.add(DeferredKind.DO, "сводка", START)
        taken = tasks.take_next()
        assert taken is not None

        tasks.release(taken)

        assert [item.state for item in tasks.items()] == [DeferredState.PENDING]

    def test_finished_item_keeps_its_outcome(self) -> None:
        clock = Clock()
        tasks = queue(clock)
        tasks.add(DeferredKind.DO, "сводка", START)
        item = tasks.take_next()
        assert item is not None

        tasks.finish(item, DeferredState.DONE, "сводка готова")

        [stored] = tasks.items()
        assert (stored.state, stored.outcome, stored.finished) == (DeferredState.DONE, "сводка готова", START)

    def test_cancel_removes_only_pending_items_with_those_ids(self) -> None:
        clock = Clock()
        tasks = queue(clock)
        first = tasks.add(DeferredKind.REMIND, "а", START + timedelta(hours=1))
        second = tasks.add(DeferredKind.REMIND, "б", START)
        running = tasks.take_next()
        assert running is not None

        cancelled = tasks.cancel([first.id, running.id, "nope"])

        assert [item.id for item in cancelled] == [first.id]
        assert [item.id for item in tasks.items()] == [second.id]

    def test_prune_forgets_old_finished_items_but_not_pending_ones(self) -> None:
        clock = Clock()
        tasks = queue(clock)
        tasks.add(DeferredKind.REMIND, "старое", START)
        waiting = tasks.add(DeferredKind.REMIND, "потом", START + timedelta(days=30))
        old = tasks.take_next()
        assert old is not None
        tasks.finish(old, DeferredState.DONE)
        clock.now += timedelta(days=8)

        tasks.prune(timedelta(days=7))

        assert [item.id for item in tasks.items()] == [waiting.id]

    def test_busy_lock_refuses_instead_of_writing_unlocked(self) -> None:
        store = MemoryList[Deferred]()
        with pytest.raises(QueueBusy):
            DeferredQueue(store, TakenLock(), Clock()).add(DeferredKind.REMIND, "а", START)
        assert store.load() == []


class TestJsonDeferredStore:
    def test_round_trip_keeps_every_field_and_the_timezone(self, tmp_path: Path) -> None:
        clock = Clock()
        tasks = queue(clock, JsonDeferredStore(tmp_path / "deferred.json"))
        tasks.add(DeferredKind.DO, "сводка", START)
        item = tasks.take_next()
        assert item is not None
        tasks.finish(item, DeferredState.FAILED, "сеть")

        [stored] = JsonDeferredStore(tmp_path / "deferred.json").load()

        assert (stored.kind, stored.text, stored.at, stored.state, stored.outcome) == (DeferredKind.DO, "сводка", START, DeferredState.FAILED, "сеть")
        assert stored.at.utcoffset() == timedelta(hours=2)

    def test_broken_file_is_set_aside_not_overwritten(self, tmp_path: Path) -> None:
        path = tmp_path / "deferred.json"
        path.write_text("[{", encoding="utf-8")

        assert JsonDeferredStore(path).load() == []
        assert list(tmp_path.glob("deferred.json.corrupt-*"))


class TestQueueHousekeeping:
    def test_interrupted_running_items_become_failed(self) -> None:
        tasks = queue(Clock())
        tasks.add(DeferredKind.DO, "сводка", START)
        assert tasks.take_next() is not None
        assert tasks.has_due()      # застрявшее — тоже работа для due

        [interrupted] = tasks.fail_interrupted("прервано")

        [stored] = tasks.items()
        assert (interrupted.text, stored.state, stored.outcome) == ("сводка", DeferredState.FAILED, "прервано")
        assert not tasks.has_due()

    def test_nothing_changed_nothing_written(self) -> None:
        store = CountingStore()
        tasks = DeferredQueue(store, Unlocked(), Clock())
        tasks.add(DeferredKind.REMIND, "потом", START + timedelta(hours=1))

        assert tasks.take_next() is None
        tasks.fail_interrupted("прервано")
        tasks.prune(timedelta(days=7))

        assert store.saves == 1      # только постановка


class CountingStore(MemoryList):
    def __init__(self) -> None:
        super().__init__()
        self.saves = 0

    def save(self, items: Sequence[Deferred]) -> None:
        self.saves += 1
        super().save(items)


class TestPeek:
    """Тик проверяет очередь без сборки ассистента — и обязан понимать файл так же, как очередь."""

    @pytest.mark.parametrize("passed", [timedelta(0), timedelta(minutes=29), timedelta(minutes=30)])
    def test_peek_agrees_with_the_queue(self, tmp_path: Path, passed: timedelta) -> None:
        clock, path = Clock(), tmp_path / "deferred.json"
        tasks = queue(clock, JsonDeferredStore(path))
        tasks.add(DeferredKind.REMIND, "духовка", START + timedelta(minutes=30))
        clock.now = START + passed

        assert peek.has_due(path, clock.now) == tasks.has_due()

    def test_peek_sees_running_and_ignores_finished(self, tmp_path: Path) -> None:
        clock, path = Clock(), tmp_path / "deferred.json"
        tasks = queue(clock, JsonDeferredStore(path))
        tasks.add(DeferredKind.DO, "сводка", START)
        item = tasks.take_next()
        assert item is not None and peek.has_due(path, START)

        tasks.finish(item, DeferredState.DONE)

        assert not peek.has_due(path, START + timedelta(days=1))

    def test_no_file_means_nothing_and_broken_file_means_let_due_look(self, tmp_path: Path) -> None:
        broken = tmp_path / "broken.json"
        broken.write_text("[{", encoding="utf-8")

        assert not peek.has_due(tmp_path / "none.json", START)
        assert peek.has_due(broken, START)
        assert peek.main(["peek", str(tmp_path / "none.json")]) == peek.NOTHING
