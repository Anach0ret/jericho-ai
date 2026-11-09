import logging
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from jericho.core import ConfirmationGate, Tool, ToolDescription, ToolRefusal, ToolRequest, ToolResult
from jericho.core.agent.consent import PhraseConsent
from jericho.core.services.adapters.confirmation_file import JsonFileConfirmationStore
from jericho.core.skills.middleware import RequireLoadedSkill
from jericho.core.testing import Confirmations
from jericho.core.tools.confirm import Confirm
from jericho.core.tools.dispatcher import ToolDispatcher
from jericho.core.tools.middleware import Refusals
from jericho.core.tools.session import CallSession


class TestJsonFileConfirmationStore:
    def test_question_is_kept_for_two_minutes(self, tmp_path: Path) -> None:
        now = [datetime(2026, 10, 10, 12, 0, tzinfo=UTC)]
        store = JsonFileConfirmationStore(tmp_path / "run" / "confirmation.json", clock=lambda: now[0])

        store.ask("close_windows", {"scope": "workspace"}, "закрыть 3 окон (стол 2)", "run-1")
        pending = store.pending()

        assert pending is not None and (pending.tool, pending.arguments, pending.asked_by) == (
            "close_windows", {"scope": "workspace"}, "run-1",
        )
        now[0] += timedelta(seconds=121)
        assert store.pending() is None

    def test_question_is_taken_once_with_what_was_agreed(self, tmp_path: Path) -> None:
        """Находка ревью: два процесса читали вопрос до удаления и оба выполняли действие."""
        path = tmp_path / "confirmation.json"
        first, second = JsonFileConfirmationStore(path), JsonFileConfirmationStore(path)
        first.ask("close_windows", {"scope": "workspace"}, "закрыть", "run-1", subject=["0xa", "0xb"])

        taken, again = first.take(), second.take()

        assert taken is not None and (taken.tool, taken.subject) == ("close_windows", ["0xa", "0xb"])
        assert (again, first.pending()) == (None, None)
        assert [item.name for item in tmp_path.iterdir()] == []

    def test_stale_question_cannot_be_taken(self, tmp_path: Path) -> None:
        now = [datetime(2026, 10, 10, 12, 0, tzinfo=UTC)]
        store = JsonFileConfirmationStore(tmp_path / "confirmation.json", clock=lambda: now[0])
        store.ask("close_windows", {}, "закрыть", "run-1")
        now[0] += timedelta(seconds=121)

        assert store.take() is None


class EraseRequest(ToolRequest):
    what: str


class Erase(Tool[EraseRequest]):
    """Ручка, которая всегда просит согласия."""

    name = "erase"
    description = ToolDescription(when="Просят стереть.", does="Стирает.", returns="Что стёрто.", refusals="needs_confirm.")
    request_type = EraseRequest

    def __init__(self, gate: ConfirmationGate, found: list[str] | None = None) -> None:
        self._gate = gate
        self.found = found if found is not None else ["файл-1"]     # что сейчас подходит под запрос
        self.erased: list[str] = []

    def _run(self, request: EraseRequest) -> ToolResult:
        consent = self._gate.consent(self.name, request.model_dump(), f"стереть {request.what}", sorted(self.found))
        if not consent.granted:
            raise ToolRefusal("needs_confirm", what=request.what, **consent.notes())
        self.erased.append(request.what)
        return ToolResult.success(erased=request.what)


def phrase(store: Confirmations, run_id: str, skill: str = "", said: str = "") -> tuple[ToolDispatcher, Erase, Confirm]:
    """Одна фраза — свой запуск: своя служба подтверждения, свой сеанс и свои ручки. `said` — что сказал пользователь:
    его, как в работе, сначала слышит вход поручения."""
    gate, session = ConfirmationGate(store, run_id), CallSession()
    PhraseConsent(gate).hear(said)
    dispatcher = ToolDispatcher([Refusals, RequireLoadedSkill], session)
    erase = Erase(gate)
    erase.skill = skill
    return dispatcher, erase, Confirm(gate, dispatcher, [erase], session)


class TestConfirm:
    def test_tool_that_needs_consent_asks_and_does_nothing(self) -> None:
        store = Confirmations()
        dispatcher, erase, _ = phrase(store, "run-1")

        result = dispatcher.call(erase, {"what": "черновик"})
        pending = store.pending()

        assert result.error == "needs_confirm" and erase.erased == []
        assert pending is not None and (pending.tool, pending.arguments, pending.summary) == (
            "erase", {"what": "черновик"}, "стереть черновик",
        )

    def test_yes_in_the_next_phrase_runs_the_saved_call(self) -> None:
        store = Confirmations()
        first, erase, _ = phrase(store, "run-1")
        first.call(erase, {"what": "черновик"})
        second, erase_again, confirm = phrase(store, "run-2", said="да")

        result = second.call(confirm, {})

        assert result.to_dict() == {"ok": True, "erased": "черновик", "confirmed": "erase"}
        assert erase_again.erased == ["черновик"] and store.pending() is None

    def test_yes_in_the_same_phrase_is_refused(self) -> None:
        store = Confirmations()
        dispatcher, erase, confirm = phrase(store, "run-1")
        dispatcher.call(erase, {"what": "черновик"})

        assert dispatcher.call(confirm, {}).error == "nothing_to_confirm" and erase.erased == []

    def test_yes_without_a_question_is_refused(self) -> None:
        dispatcher, _, confirm = phrase(Confirmations(), "run-1")

        assert dispatcher.call(confirm, {}).error == "nothing_to_confirm"

    def test_consent_covers_one_call_only(self) -> None:
        store = Confirmations()
        first, erase, _ = phrase(store, "run-1")
        first.call(erase, {"what": "черновик"})
        second, erase_again, confirm = phrase(store, "run-2", said="да")
        second.call(confirm, {})

        assert second.call(erase_again, {"what": "черновик"}).error == "needs_confirm"
        assert erase_again.erased == ["черновик"]

    def test_confirmed_skill_tool_runs_without_loading_the_skill(self) -> None:
        """Во фразе «да» модель ничего не выбирает — руководство навыка ей не нужно."""
        store = Confirmations()
        ConfirmationGate(store, "run-1").consent("erase", {"what": "черновик"}, "стереть черновик", ["файл-1"])
        dispatcher, erase, confirm = phrase(store, "run-2", skill="notes", said="да")

        assert dispatcher.call(erase, {"what": "заметку"}).error == "skill_not_loaded"
        assert dispatcher.call(confirm, {}).ok and erase.erased == ["черновик"]


class TestConsentIsForWhatWasNamed:
    """Находка ревью: хранились имя ручки и параметры, а объекты после «да» выбирались заново — могли быть уже другими."""

    def test_yes_does_not_cover_a_world_that_has_changed(self, caplog: pytest.LogCaptureFixture) -> None:
        store = Confirmations()
        first, erase, _ = phrase(store, "run-1")
        first.call(erase, {"what": "черновик"})
        second, erase_again, confirm = phrase(store, "run-2", said="да")
        erase_again.found = ["файл-1", "файл-2"]        # между вопросом и «да» появилось ещё одно

        with caplog.at_level(logging.WARNING, logger="jericho"):
            result = second.call(confirm, {})

        assert (result.error, erase_again.erased) == ("needs_confirm", [])
        assert "изменилось" in str(result.data["changed"])
        assert caplog.records[-1].getMessage() == "confirmation_changed"

    def test_after_a_change_the_question_is_asked_anew_and_the_next_yes_works(self) -> None:
        store = Confirmations()
        first, erase, _ = phrase(store, "run-1")
        first.call(erase, {"what": "черновик"})
        second, erase_again, confirm = phrase(store, "run-2", said="да")
        erase_again.found = ["файл-1", "файл-2"]
        second.call(confirm, {})
        third, erase_third, confirm_third = phrase(store, "run-3", said="да")
        erase_third.found = ["файл-2", "файл-1"]        # то же самое, порядок не важен

        assert third.call(confirm_third, {}).ok and erase_third.erased == ["черновик"]

    def test_same_world_is_recognised_after_the_question_has_been_through_a_file(self, tmp_path: Path) -> None:
        store = JsonFileConfirmationStore(tmp_path / "confirmation.json")
        ConfirmationGate(store, "run-1").consent("erase", {"what": "черновик"}, "стереть черновик", ("файл-1",))
        gate = ConfirmationGate(store, "run-2")
        gate.user_said_yes()
        gate.grant()

        assert gate.consent("erase", {"what": "черновик"}, "стереть черновик", ("файл-1",)).granted


class TestNewQuestion:
    def test_new_question_about_something_else_drops_the_old_one_aloud(self, caplog: pytest.LogCaptureFixture) -> None:
        """Находка ревью: хранится один вопрос, и новый затирал прежний молча."""
        store = Confirmations()
        dispatcher, erase, _ = phrase(store, "run-1")
        dispatcher.call(erase, {"what": "черновик"})

        with caplog.at_level(logging.WARNING, logger="jericho"):
            result = dispatcher.call(erase, {"what": "архив"})

        pending = store.pending()
        assert result.data["replaced"] == "прежний вопрос снят: стереть черновик"
        assert pending is not None and pending.summary == "стереть архив"
        assert caplog.records[-1].getMessage() == "confirmation_replaced"

    def test_same_question_asked_twice_is_not_a_replacement(self) -> None:
        store = Confirmations()
        dispatcher, erase, _ = phrase(store, "run-1")
        dispatcher.call(erase, {"what": "черновик"})

        assert "replaced" not in dispatcher.call(erase, {"what": "черновик"}).data


class TestGrantIsTakenOnce:
    def test_second_run_finds_nothing_after_the_first_has_taken_the_question(self) -> None:
        store = Confirmations()
        ConfirmationGate(store, "run-1").consent("erase", {"what": "черновик"}, "стереть черновик")

        second = ConfirmationGate(store, "run-2")
        second.user_said_yes()
        third = ConfirmationGate(store, "run-3")

        assert second.grant() is not None
        third.user_said_yes()
        assert third.grant() is None


class TestYesIsHeardByCode:
    """«Да» удостоверяет код по фразе пользователя, а не вызов модели (ревью R02)."""

    def test_model_calling_confirm_after_no_gets_nothing_done(self) -> None:
        store = Confirmations()
        phrase(store, "run-1")[0].call(Erase(ConfirmationGate(store, "run-1")), {"what": "черновик"})
        dispatcher, erase, confirm = phrase(store, "run-2", said="Нет, не надо.")

        result = dispatcher.call(confirm, {})

        assert result.error == "nothing_to_confirm" and erase.erased == [] and store.pending() is None   # «нет» снял вопрос

    def test_model_calling_confirm_on_another_phrase_is_refused_and_the_question_waits(self) -> None:
        store = Confirmations()
        phrase(store, "run-1")[0].call(Erase(ConfirmationGate(store, "run-1")), {"what": "черновик"})
        dispatcher, erase, confirm = phrase(store, "run-2", said="а что там с погодой")

        assert dispatcher.call(confirm, {}).error == "no_yes_from_user" and erase.erased == []
        assert store.pending() is not None

    @pytest.mark.parametrize("said", ["да", "Да.", "давай!", "да, пожалуйста", "подтверждаю"])
    def test_plain_yes_in_any_dress_is_heard(self, said: str) -> None:
        store = Confirmations()
        ConfirmationGate(store, "run-1").consent("erase", {"what": "черновик"}, "стереть черновик")

        assert PhraseConsent(ConfirmationGate(store, "run-2")).hear(said).answer == "yes"

    def test_yes_with_another_command_is_not_consent(self) -> None:
        store = Confirmations()
        ConfirmationGate(store, "run-1").consent("erase", {"what": "черновик"}, "стереть черновик")

        assert not PhraseConsent(ConfirmationGate(store, "run-2")).hear("да, и ещё открой почту")


def heard(said: str) -> str:
    """Что код услышал во фразе на ждущий вопрос «стереть черновик»."""
    store = Confirmations()
    ConfirmationGate(store, "run-1").consent("erase", {"what": "черновик"}, "стереть черновик")
    return PhraseConsent(ConfirmationGate(store, "run-2")).hear(said).answer


class TestPoliteWords:
    """«Пожалуйста» и «please» не меняют ответ, но и не склеивают согласие из чужих слов."""

    @pytest.mark.parametrize(("said", "answer"), [
        ("да, пожалуйста", "yes"),
        ("пожалуйста, да", "yes"),
        ("Да пожалуйста пожалуйста!", "yes"),
        ("да,\n\tпожалуйста", "yes"),
        ("yes please", "yes"),
        ("Please, go ahead.", "yes"),
        ("да, please, отправляй", "yes"),
        ("нет, пожалуйста", "no"),
        ("Please cancel", "no"),
        ("пожалуйста", ""),
        ("please please", ""),
        ("да пожалуйстаааа", ""),
        ("пожалуйстада", ""),
        ("да_пожалуйста", ""),
        ("да, пожалуйста, и открой почту", ""),
        ("пожалуйста не надо, да", ""),
    ])
    def test_polite_word_is_dropped_only_as_a_whole_word(self, said: str, answer: str) -> None:
        assert heard(said) == answer

    def test_long_whitespace_is_heard_in_linear_time(self) -> None:
        """Sonar S8786: `\\s*\\b(?:пожалуйста|please)\\b\\s*` на длинных пробелах росла квадратично.

        Проба — в отдельном процессе с конечным сроком: зависание не вешает основной прогон тестов.
        """
        probe = (
            "from tests.core.test_confirmation import heard\n"
            "assert heard('да' + ' ' * 300_000 + 'x') == ''\n"
        )
        subprocess.run([sys.executable, "-c", probe], check=True, timeout=20)


class TestExpiredQuestion:
    """У вопроса «да?» свой срок, и его конец не немой."""

    def store(self, tmp_path: Path, now: list[datetime], minutes: int = 30) -> JsonFileConfirmationStore:
        return JsonFileConfirmationStore(tmp_path / "confirmation.json", timedelta(minutes=minutes), clock=lambda: now[0])

    def test_question_waits_its_own_term_then_is_taken_as_expired_once(self, tmp_path: Path) -> None:
        now = [datetime(2026, 10, 28, 14, 0, tzinfo=UTC)]
        store = self.store(tmp_path, now)
        store.ask("restart", {"name": "shop"}, "перезапустить shop", "run-1")

        now[0] += timedelta(minutes=29)
        assert store.pending() is not None and store.take_expired() is None      # ещё в силе — «истёк» не забирает
        now[0] += timedelta(minutes=2)
        assert store.pending() is None
        expired = store.take_expired()
        assert expired is not None and expired.summary == "перезапустить shop" and store.take_expired() is None

    def test_reminder_mark_survives_the_file(self, tmp_path: Path) -> None:
        now = [datetime(2026, 10, 28, 14, 0, tzinfo=UTC)]
        store = self.store(tmp_path, now)
        store.ask("restart", {}, "перезапустить", "run-1")

        store.mark_reminded()

        assert self.store(tmp_path, now).pending().reminded is True  # pyright: ignore[reportOptionalMemberAccess]

    @pytest.mark.parametrize("said", ["да", "нет"])
    def test_answer_after_the_term_says_expired_and_does_nothing(self, tmp_path: Path, said: str, caplog: pytest.LogCaptureFixture) -> None:
        from jericho.core.agent.consent import AnswerWithoutModel

        now = [datetime(2026, 10, 28, 14, 5, tzinfo=UTC)]
        store = self.store(tmp_path, now, minutes=2)
        ConfirmationGate(store, "run-1").consent("erase", {"what": "черновик"}, "стереть черновик")
        now[0] += timedelta(minutes=5)
        done: list[str] = []
        answer = AnswerWithoutModel(PhraseConsent(ConfirmationGate(store, "run-2")), confirm=lambda: done.append("x") or ToolResult.success())

        with caplog.at_level(logging.WARNING):
            heard = answer.hear(said)
        reply = answer(heard, None).reply  # pyright: ignore[reportArgumentType]

        assert heard.answer == "expired" and answer.answers(heard) and done == []
        assert reply.message == "Вопрос от 14:05 истёк: стереть черновик — ничего не сделано. Если нужно, попроси ещё раз."
        assert [record.getMessage() for record in caplog.records] == ["confirmation_expired"]

    def test_other_phrase_leaves_the_expired_question_for_the_watch(self, tmp_path: Path) -> None:
        now = [datetime(2026, 10, 28, 14, 0, tzinfo=UTC)]
        store = self.store(tmp_path, now, minutes=2)
        ConfirmationGate(store, "run-1").consent("erase", {}, "стереть")
        now[0] += timedelta(minutes=5)

        assert PhraseConsent(ConfirmationGate(store, "run-2")).hear("а что с погодой").answer == ""
        assert store.take_expired() is not None
