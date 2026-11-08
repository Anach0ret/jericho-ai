"""Личные данные (решения владельца 23.10.2026): запасной модели — нет; пересказ — в папку сеанса, не в журнал."""

import logging
from datetime import datetime
from pathlib import Path
from typing import ClassVar

import pytest

from jericho.core import ConfirmationGate, ForeignText, Risk, Tool, ToolDescription, ToolRequest, ToolResult
from jericho.core.agent.active_backend import ActiveBackend
from jericho.core.agent.entities import AgentReply, BackendAnswer, ReplyStatus
from jericho.core.agent.fallback import FallbackBackend, NamedBackend
from jericho.core.agent.handle_phrase import HandlePhrase
from jericho.core.agent.phrase_journal import PhraseJournal
from jericho.core.journal.entities import JournalEntry
from jericho.core.journal.reply_vault import ReplyVault
from jericho.core.services.adapters.json_file import JsonStateFile
from jericho.core.testing import FakeBackend, builder
from jericho.core.testing.fakes import Confirmations
from jericho.core.tools.dispatcher import ToolDispatcher
from jericho.core.tools.middleware import Refusals
from jericho.core.tools.policy import RiskPolicy


class ReadChat(Tool[ToolRequest]):
    name = "read_chat"
    risk = Risk.READ
    private: ClassVar[tuple[str, ...]] = ("messages",)
    description = ToolDescription(when="тест", does="тест", returns="тест", refusals="тест")
    request_type = ToolRequest

    def _run(self, request: ToolRequest) -> ToolResult:
        return ToolResult.success(messages=["буду в 7"], memo="прочитал чат")


def call(active: str, allowed: tuple[str, ...] | None = ("claude_cli",), main: str = "claude_cli") -> ToolResult:
    policy = RiskPolicy(ConfirmationGate(Confirmations(), "run-1"), private_backends=allowed, active=ActiveBackend(active, main))
    return ToolDispatcher((Refusals,), policy=policy).call(ReadChat(), {})


class TestPrivateDataPolicy:
    def test_spare_model_does_not_get_private_data(self) -> None:
        result = call("openai_api")

        assert result.error == RiskPolicy.UNTRUSTED_MODEL and result.data["backend"] == "openai_api"

    def test_trusted_model_and_no_model_get_it(self) -> None:
        assert call("claude_cli").ok
        assert call("").ok                       # человек в терминале или кнопка сценария: данные остаются на машине

    def test_without_the_list_only_the_main_backend_gets_it(self) -> None:
        """Список не назван — основной бэкенд, а не любой: README так и обещал (ревью 02.11.2026, П5 №7)."""
        assert call("claude_cli", allowed=None).ok
        assert call("openai_api", allowed=None).error == RiskPolicy.UNTRUSTED_MODEL
        assert call("openai_api", allowed=None, main="openai_api").ok      # выбрали вручную — он и основной

    def test_a_spare_named_in_the_list_gets_it(self) -> None:
        assert call("openai_api", allowed=("claude_cli", "openai_api")).ok

    def test_fallback_names_the_backend_that_answers(self) -> None:
        from jericho.core.agent.protocols import ModelUnavailable

        class Down:
            def ask(self, system_prompt: str, phrase: str) -> BackendAnswer:
                raise ModelUnavailable("лимит подписки")

        class Spare:
            def __init__(self, active: ActiveBackend) -> None:
                self.seen = ""
                self._active = active

            def ask(self, system_prompt: str, phrase: str) -> BackendAnswer:
                self.seen = self._active.name
                return BackendAnswer({"status": "done", "message": "ок"})

        class NothingDone:
            def done(self) -> tuple[str, ...]:
                return ()

        active = ActiveBackend()
        spare = Spare(active)
        FallbackBackend([NamedBackend("claude_cli", Down()), NamedBackend("openai_api", spare)], NothingDone(), active).ask("", "фраза")

        assert spare.seen == "openai_api"


class TestPrivateReplies:
    def test_journal_keeps_the_memo_and_the_session_keeps_the_reply(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        vault = ReplyVault(JsonStateFile(tmp_path / "private-replies.json"))
        backend = FakeBackend({"status": "done", "message": "Марина пишет: буду в 7"})
        handle = HandlePhrase(builder(), backend, journal=PhraseJournal(lambda: ("прочитал чат «Марина»: 1 сообщ.",), vault, "run-7"))

        with caplog.at_level(logging.INFO, logger="jericho"):
            reply = handle.execute("что пишет Марина")

        journaled = caplog.records[-1].data  # pyright: ignore[reportAttributeAccessIssue]
        assert (journaled["message"], journaled["private"]) == ("прочитал чат «Марина»: 1 сообщ.", True)
        assert reply == AgentReply(ReplyStatus.DONE, "Марина пишет: буду в 7", private=True)     # человеку — целиком
        assert vault.get("run-7") == ("Марина пишет: буду в 7", "")

    def test_ordinary_phrase_is_journaled_as_is(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.INFO, logger="jericho"):
            reply = HandlePhrase(builder(), FakeBackend({"status": "done", "message": "Открыл YouTube"})).execute("открой ютуб")

        assert caplog.records[-1].data["message"] == "Открыл YouTube" and not reply.private  # pyright: ignore[reportAttributeAccessIssue]

    def test_vault_keeps_only_the_last_replies(self, tmp_path: Path) -> None:
        vault = ReplyVault(JsonStateFile(tmp_path / "private-replies.json"))
        for number in range(ReplyVault.KEEP + 2):
            vault.keep(f"run-{number}", AgentReply(ReplyStatus.DONE, f"ответ {number}"))

        assert vault.get("run-0") is None and vault.get(f"run-{ReplyVault.KEEP + 1}") == (f"ответ {ReplyVault.KEEP + 1}", "")

    def test_window_shows_the_full_reply_while_the_session_lives(self, tmp_path: Path) -> None:
        from tests.core.test_status_command import Journal, command

        vault = ReplyVault(JsonStateFile(tmp_path / "private-replies.json"))
        vault.keep("run-7", AgentReply(ReplyStatus.DONE, "Марина пишет: буду в 7"))
        entry = JournalEntry(datetime(2026, 10, 23, 18, 30), "phrase", details={"phrase": "что пишет Марина", "status": "done", "message": "прочитал чат", "private": True}, run="run-7")
        assert command(Journal(entry), vault=vault).snapshot()["conversation"][0]["message"] == "Марина пишет: буду в 7"


class OpenUrl(Tool[ToolRequest]):
    name = "open_url"
    risk = Risk.NAVIGATE
    outbound = True
    description = ToolDescription(when="тест", does="тест", returns="тест", refusals="тест")
    request_type = ToolRequest

    def _run(self, request: ToolRequest) -> ToolResult:
        return ToolResult.success()


class Mail(OpenUrl):
    name = "send_mail"
    risk = Risk.EFFECT


class TestOutboundAfterPrivateData:
    """Внедрённая в переписку ссылка не унесёт её в адресе: после личных данных выносить наружу — только с «да»."""

    def dispatcher(self, attended: bool = True) -> ToolDispatcher:
        policy = RiskPolicy(ConfirmationGate(Confirmations(), "run-1", attended=attended), active=ActiveBackend("claude_cli", "claude_cli"))
        return ToolDispatcher((Refusals,), policy=policy)

    def test_link_is_opened_freely_without_private_data(self) -> None:
        assert self.dispatcher().call(OpenUrl(), {}).ok

    def test_after_private_data_it_needs_yes(self) -> None:
        dispatcher = self.dispatcher()

        assert dispatcher.call(ReadChat(), {}).ok
        result = dispatcher.call(OpenUrl(), {})

        assert result.error == "needs_confirm" and "личная переписка" in str(result.data)

    def test_effect_question_says_private_data_was_read(self) -> None:
        """Отправка, которую спрашивает каркас (EFFECT, ASK), — с той же пометкой: что уйдёт после чтения переписки."""
        dispatcher = self.dispatcher()

        dispatcher.call(ReadChat(), {})
        result = dispatcher.call(Mail(), {})

        assert result.error == "needs_confirm" and "личная переписка" in str(result.data)

    def test_without_a_person_it_is_refused(self) -> None:
        dispatcher = self.dispatcher(attended=False)

        dispatcher.call(ReadChat(), {})

        assert dispatcher.call(OpenUrl(), {}).error == RiskPolicy.NOBODY_TO_ASK


class ReadFile(Tool[ToolRequest]):
    name = "read_file"
    risk = Risk.READ
    local = True
    description = ToolDescription(when="тест", does="тест", returns="тест", refusals="тест")
    request_type = ToolRequest

    def _run(self, request: ToolRequest) -> ToolResult:
        return ToolResult.success(text="host_key: …")


class TestOutboundAfterLocalFiles:
    """Аудит 27.10.2026: «чужая страница → файл → открыть ссылку» шло без вопроса. После файла с машины и чужого
    текста в одной фразе вынос наружу — только с «да»; одно без другого — как раньше, без вопроса."""

    def dispatcher(self, foreign: ForeignText, attended: bool = True) -> ToolDispatcher:
        gate = ConfirmationGate(Confirmations(), "run-1", attended=attended)
        return ToolDispatcher((Refusals,), policy=RiskPolicy(gate, active=ActiveBackend("claude_cli", "claude_cli"), foreign=foreign))

    def test_file_then_page_link_needs_yes(self) -> None:
        foreign = ForeignText()
        dispatcher = self.dispatcher(foreign)

        dispatcher.call(ReadFile(), {})
        foreign.read_from("browser")
        result = dispatcher.call(OpenUrl(), {})

        assert result.error == "needs_confirm" and "файлы с машины" in str(result.data)

    def test_file_alone_or_page_alone_is_free(self) -> None:
        only_file = self.dispatcher(ForeignText())
        only_file.call(ReadFile(), {})
        page = ForeignText()
        page.read_from("browser")

        assert only_file.call(OpenUrl(), {}).ok and self.dispatcher(page).call(OpenUrl(), {}).ok

    def test_without_a_person_it_is_refused(self) -> None:
        foreign = ForeignText()
        foreign.read_from("browser")
        dispatcher = self.dispatcher(foreign, attended=False)
        dispatcher.call(ReadFile(), {})

        assert dispatcher.call(OpenUrl(), {}).error == RiskPolicy.NOBODY_TO_ASK
