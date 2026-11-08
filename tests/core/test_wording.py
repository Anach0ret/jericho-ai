"""Язык ассистента (`Settings.language`): что ядро говорит само и какие «да» и «нет» слышит."""

import pytest
from pydantic import ValidationError

from jericho.core.agent.consent import AnswerWithoutModel, AskedQuestion, PhraseConsent
from jericho.core.agent.entities import AgentReply, ReplyStatus
from jericho.core.agent.handle_phrase import HandlePhrase
from jericho.core.agent.wording import ENGLISH, RUSSIAN
from jericho.core.conf.settings import Settings
from jericho.core.prompting.builder import PromptBuilder
from jericho.core.services.confirmation import ConfirmationGate
from jericho.core.testing import Confirmations, FakeBackend, builder
from jericho.core.testing.fakes import Source
from jericho.core.tools.result import ToolResult

QUESTION = "restart the shop container"


def answered(phrase: str) -> AgentReply:
    store = Confirmations()
    ConfirmationGate(store, "run-1").consent("restart_container", {"container": "shop"}, QUESTION)
    consent = AnswerWithoutModel(PhraseConsent(ConfirmationGate(store, "run-2")), lambda: ToolResult.success(), ENGLISH)
    return HandlePhrase(builder(), FakeBackend({"status": "done", "message": "model"}), consent=consent, wording=ENGLISH).execute(phrase)


class TestEnglish:
    @pytest.mark.parametrize("phrase", ["okay", "Go ahead, please", "yes do it"])
    def test_english_yes_runs_the_call_and_says_so_in_english(self, phrase: str) -> None:
        assert answered(phrase) == AgentReply(ReplyStatus.DONE, f"Done: {QUESTION}")

    @pytest.mark.parametrize("phrase", ["nope", "don't", "no thanks"])
    def test_english_no_cancels(self, phrase: str) -> None:
        assert answered(phrase) == AgentReply(ReplyStatus.DONE, f"Cancelled: {QUESTION}")

    def test_russian_assistant_hears_english_yes_too(self) -> None:
        store = Confirmations()
        ConfirmationGate(store, "run-1").consent("restart_container", {"container": "shop"}, QUESTION)

        assert PhraseConsent(ConfirmationGate(store, "run-2")).hear("sure").answer == "yes"

    def test_buttons_of_the_question_follow_the_language(self) -> None:
        gate = ConfirmationGate(Confirmations(), "run-1")
        gate.consent("restart_container", {"container": "shop"}, QUESTION)

        reply = AskedQuestion(gate, ENGLISH).settle(AgentReply(ReplyStatus.CLARIFY, "Restart?"))

        assert reply.options == ("Yes", "No")

    def test_failure_and_busy_are_in_the_language(self) -> None:
        handle = HandlePhrase(builder(), FakeBackend(error="boom"), wording=ENGLISH)

        assert handle.execute("restart shop") == AgentReply(ReplyStatus.FAILED, ENGLISH.failure)
        assert handle.busy.message == ENGLISH.busy

    def test_model_is_told_to_answer_in_english(self) -> None:
        prompt = PromptBuilder(Source(), (), ["desktop"], language_note=ENGLISH.reply_language).build()

        assert prompt.endswith(ENGLISH.reply_language)


class TestSetting:
    def test_russian_by_default(self) -> None:
        assert Settings().language == "ru" and RUSSIAN.yes == "Да"

    def test_unknown_language_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            Settings(language="de")  # pyright: ignore[reportArgumentType]
