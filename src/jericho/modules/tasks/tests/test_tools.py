from datetime import timedelta

from jericho.core.services.adapters.memory_list import MemoryList
from jericho.core.services.confirmation import ConfirmationGate
from jericho.core.services.lock import Unlocked
from jericho.core.testing import Confirmations, execute, say_yes
from jericho.core.tools.dispatcher import ToolDispatcher
from jericho.core.tools.middleware import Journal, Refusals
from jericho.core.tools.policy import RiskPolicy
from jericho.modules.tasks.entities import Deferred, DeferredKind, DeferredState
from jericho.modules.tasks.queue import DeferredQueue
from jericho.modules.tasks.settings import DeferredSettings
from jericho.modules.tasks.tests.fakes import START, Clock
from jericho.modules.tasks.tools import CancelScheduled, ListScheduled, Schedule

TOMORROW_9 = (START + timedelta(hours=13)).isoformat()
REMIND = {"kind": "remind", "text": "выключить духовку", "at": (START + timedelta(minutes=30)).isoformat()}


class Phrases:
    """Ручки одной очереди; каждая фраза — свой запуск со своей службой подтверждения, как в работе."""

    def __init__(self, settings: DeferredSettings | None = None) -> None:
        self.clock = Clock()
        self.queue = DeferredQueue(MemoryList[Deferred](), Unlocked(), self.clock)
        self._confirmations = Confirmations()
        self._settings = settings or DeferredSettings(enabled=True)
        self._phrase = 0
        self.next_phrase()

    def next_phrase(self) -> None:
        self._phrase += 1
        self.gate = ConfirmationGate(self._confirmations, f"run-{self._phrase}")
        self.schedule = Schedule(self.queue, self.gate, self._settings, self.clock)
        self.cancel = CancelScheduled(self.queue, self.gate)
        self.list = ListScheduled(self.queue, self.clock)


class TestSchedule:
    def test_first_call_asks_with_the_time_spoken_by_the_code(self) -> None:
        phrases = Phrases()

        result = execute(phrases.schedule, {"kind": "do", "text": "собери сводку по почте", "at": TOMORROW_9})

        assert (result.ok, result.error) == (False, "needs_confirm")
        assert result.data["summary"] == "выполнить «собери сводку по почте» — завтра, чт 22 октября, 09:00 (через 13 ч)"
        assert phrases.queue.items() == []

    def test_yes_in_the_next_phrase_puts_it_in_the_queue(self) -> None:
        phrases = Phrases()
        execute(phrases.schedule, REMIND)
        phrases.next_phrase()

        result = say_yes(phrases.gate, phrases.schedule)

        assert result.ok and result.data["when"] == "сегодня, ср 21 октября, 20:30 (через 30 мин)"
        [item] = phrases.queue.items()
        assert (item.id, item.kind, item.text, item.state) == (result.data["id"], DeferredKind.REMIND, "выключить духовку", DeferredState.PENDING)

    def test_without_a_person_nothing_can_be_scheduled_even_if_the_project_allows_effects(self) -> None:
        """Задача по расписанию не ставит задачи: иначе они размножались бы мимо «да»."""
        phrases = Phrases()
        nobody = ConfirmationGate(Confirmations(), "task-run", attended=False)
        schedule = Schedule(phrases.queue, nobody, DeferredSettings(enabled=True), phrases.clock)
        allowed = ToolDispatcher([Journal, Refusals], policy=RiskPolicy(nobody, unattended_effects=("schedule",)))

        refused = ToolDispatcher([Journal, Refusals], policy=RiskPolicy(nobody)).call(schedule, REMIND)
        still_refused = allowed.call(schedule, REMIND)

        assert refused.error == RiskPolicy.NOBODY_TO_ASK
        assert still_refused.error == "needs_confirm" and "nobody" in still_refused.data
        assert phrases.queue.items() == []

    def test_time_without_a_zone_is_a_broken_parameter(self) -> None:
        result = execute(Phrases().schedule, {**REMIND, "at": "2026-10-22T09:00:00"})

        assert result.error == ToolDispatcher.INVALID_PARAMETERS

    def test_past_far_and_full_are_refused_before_asking(self) -> None:
        phrases = Phrases(DeferredSettings(enabled=True, max_pending=1))
        past = execute(phrases.schedule, {**REMIND, "at": (START - timedelta(hours=1)).isoformat()})
        far = execute(phrases.schedule, {**REMIND, "at": (START + timedelta(days=400)).isoformat()})
        phrases.queue.add(DeferredKind.REMIND, "уже ждёт", START + timedelta(hours=1))
        full = execute(phrases.schedule, REMIND)

        assert [past.error, far.error, full.error] == ["in_past", "too_far", "too_many"]


class TestListAndCancel:
    def test_list_shows_pending_with_the_time_and_finished_with_the_outcome(self) -> None:
        phrases = Phrases()
        phrases.queue.add(DeferredKind.DO, "сводка", START)
        done = phrases.queue.take_next()
        assert done is not None
        phrases.queue.finish(done, DeferredState.DONE, "сводка готова")
        waiting = phrases.queue.add(DeferredKind.REMIND, "духовка", START + timedelta(minutes=30))

        result = execute(phrases.list, {})

        assert result.data["pending"] == [{"id": waiting.id, "kind": "remind", "text": "духовка", "when": "сегодня, ср 21 октября, 20:30 (через 30 мин)"}]
        assert result.data["finished"] == [{"id": done.id, "kind": "do", "text": "сводка", "state": "done", "outcome": "сводка готова"}]

    def test_one_is_cancelled_at_once(self) -> None:
        phrases = Phrases()
        item = phrases.queue.add(DeferredKind.REMIND, "духовка", START + timedelta(hours=1))

        result = execute(phrases.cancel, {"ids": [item.id]})

        assert result.data["cancelled"] == ["духовка"] and phrases.queue.items() == []

    def test_several_wait_for_yes(self) -> None:
        phrases = Phrases()
        ids = [phrases.queue.add(DeferredKind.REMIND, text, START + timedelta(hours=1)).id for text in ("а", "б")]

        asked = execute(phrases.cancel, {"ids": ids})
        phrases.next_phrase()
        result = say_yes(phrases.gate, phrases.cancel)

        assert asked.error == "needs_confirm" and asked.data["summary"] == "снять 2: а; б"
        assert result.data["cancelled"] == ["а", "б"]

    def test_unknown_id_is_refused_and_nothing_is_cancelled(self) -> None:
        phrases = Phrases()
        item = phrases.queue.add(DeferredKind.REMIND, "духовка", START + timedelta(hours=1))

        result = execute(phrases.cancel, {"ids": [item.id, "abcdef"]})

        assert (result.error, result.data["ids"]) == ("not_found", ["abcdef"])
        assert len(phrases.queue.items()) == 1
