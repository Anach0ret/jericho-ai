"""«Да» и «нет» на ждущий вопрос — без модели: код их распознал, вызов выполняет сам, ответ собирает сам."""

from jericho.core.agent.consent import AnswerWithoutModel, AskedQuestion, PhraseConsent
from jericho.core.agent.entities import AgentReply, BackendAnswer, ReplyStatus
from jericho.core.agent.handle_phrase import HandlePhrase
from jericho.core.services.confirmation import ConfirmationGate
from jericho.core.testing import Confirmations, FakeBackend, builder
from jericho.core.tools.result import ToolResult

QUESTION = "перезапустить контейнер portfolio_backend"


class Confirm:
    def __init__(self, result: ToolResult) -> None:
        self.calls = 0
        self._result = result

    def __call__(self) -> ToolResult:
        self.calls += 1
        return self._result


def phrase(answer: str, confirm: Confirm | None) -> tuple[AgentReply, FakeBackend]:
    """Вопрос задан прошлой фразой (run-1), ответ — этой (run-2)."""
    store = Confirmations()
    ConfirmationGate(store, "run-1").consent("restart_container", {"container": "portfolio_backend"}, QUESTION)
    gate = ConfirmationGate(store, "run-2")
    backend = FakeBackend({"status": "done", "message": "модель ответила"})
    handle = HandlePhrase(builder(), backend, consent=AnswerWithoutModel(PhraseConsent(gate), confirm))
    return handle.execute(answer), backend


class TestConsentWithoutModel:
    def test_yes_runs_the_confirmed_call_and_names_it(self) -> None:
        confirm = Confirm(ToolResult.success(detail="запущено в фоне", confirmed="restart_container"))

        reply, backend = phrase("да", confirm)

        assert confirm.calls == 1 and backend.asked == []
        assert reply == AgentReply(ReplyStatus.DONE, "Перезапустить контейнер portfolio_backend — запущено в фоне")

    def test_no_cancels_without_the_model(self) -> None:
        confirm = Confirm(ToolResult.success())

        reply, backend = phrase("нет", confirm)

        assert confirm.calls == 0 and backend.asked == []
        assert reply == AgentReply(ReplyStatus.DONE, f"Отменил: {QUESTION}")

    def test_refused_call_says_why_in_words(self) -> None:
        confirm = Confirm(ToolResult.failure("not_found", detail="контейнера больше нет"))

        reply, _ = phrase("да", confirm)

        assert reply == AgentReply(ReplyStatus.REFUSED, f"Не сделано: {QUESTION} — контейнера больше нет")

    def test_changed_world_is_a_new_question_not_a_refusal(self) -> None:
        """П1 №4: подтверждённая ручка спросила заново — ответ `clarify`, вопрос ждёт следующего «да»."""
        confirm = Confirm(ToolResult.failure("needs_confirm", changed="с прошлого вопроса всё изменилось"))

        reply, _ = phrase("да", confirm)

        assert reply.status is ReplyStatus.CLARIFY

    def test_without_confirm_the_model_answers_as_before(self) -> None:
        reply, backend = phrase("да", None)

        assert len(backend.asked) == 1 and reply.message == "модель ответила"

    def test_other_phrases_still_go_to_the_model(self) -> None:
        reply, backend = phrase("да, и ещё открой почту", Confirm(ToolResult.success()))

        assert len(backend.asked) == 1 and reply.message == "модель ответила"


class AskingBackend(FakeBackend):
    """Модель, у которой ручка в этой фразе задала вопрос «да?», — а ответила она так, как ответила."""

    def __init__(self, gate: ConfirmationGate, structured: dict[str, object]) -> None:
        super().__init__(structured)
        self._gate = gate

    def ask(self, system_prompt: str, phrase: str) -> BackendAnswer:
        self._gate.consent("remember", {"name": "расписание курса"}, "запомнить «расписание курса»")
        return super().ask(system_prompt, phrase)


def asking(store: Confirmations, structured: dict[str, object]) -> AgentReply:
    gate = ConfirmationGate(store, "run-1")
    return HandlePhrase(builder(), AskingBackend(gate, structured), question=AskedQuestion(gate)).execute("открой тест")


class TestAskedQuestion:
    def test_question_reaches_the_user_with_the_yes_and_no_the_core_hears(self) -> None:
        """Журнал 29.10.2026: модель подписала кнопку «Да, отправить», а нажатие на неё ядро не приняло."""
        store = Confirmations()

        reply = asking(store, {"status": "clarify", "message": "Запомнить расписание?", "options": ["Да, запомни", "Не надо"]})

        assert reply.options == ("Да", "Нет")
        assert store.pending() is not None

    def test_question_the_reply_did_not_ask_is_withdrawn(self) -> None:
        """Журнал 29.10.2026: ответ «Открыл тест» вопроса не задал, а «да» на следующий вопрос модели записало заметку."""
        store = Confirmations()

        reply = asking(store, {"status": "done", "message": "Открыл тест"})
        later = PhraseConsent(ConfirmationGate(store, "run-2")).hear("да")

        assert reply.status is ReplyStatus.DONE
        assert store.pending() is None and not later

    def test_without_a_question_the_reply_is_untouched(self) -> None:
        reply = HandlePhrase(builder(), FakeBackend({"status": "clarify", "message": "Какой тест?", "options": ["Урок 2", "Урок 6"]}),
                             question=AskedQuestion(ConfirmationGate(Confirmations(), "run-1"))).execute("пройди тест")

        assert reply.options == ("Урок 2", "Урок 6")
