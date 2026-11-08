from datetime import datetime

import pytest

from jericho.core.agent.entities import BackendAnswer
from jericho.core.agent.fallback import FallbackBackend, NamedBackend
from jericho.core.agent.protocols import AgentBackendError, ModelUnavailable
from jericho.core.journal.entities import JournalEntry
from jericho.core.journal.run_actions import JournalRunActions
from jericho.core.tools.risk import Risk

DONE = {"status": "done", "message": "Готово"}


class Backend:
    def __init__(self, error: AgentBackendError | None = None) -> None:
        self._error = error
        self.asked = 0

    def ask(self, system_prompt: str, phrase: str) -> BackendAnswer:
        self.asked += 1
        if self._error is not None:
            raise self._error
        return BackendAnswer(DONE, {"num_turns": 2})


class Actions:
    def __init__(self, *done: str) -> None:
        self._done = done

    def done(self) -> tuple[str, ...]:
        return self._done


def chain(*backends: Backend, actions: Actions | None = None) -> FallbackBackend:
    named = [NamedBackend(name, backend) for name, backend in zip(("claude_cli", "openai_api", "anthropic_api"), backends, strict=False)]
    return FallbackBackend(named, actions or Actions())


class TestFallbackBackend:
    def test_limit_of_the_main_model_hands_the_phrase_to_the_spare(self) -> None:
        spare = Backend()

        answer = chain(Backend(ModelUnavailable("usage limit reached")), spare).ask("ПРОМПТ", "открой ютуб")

        assert answer == BackendAnswer(DONE, {"num_turns": 2, "backend": "openai_api"}) and spare.asked == 1

    def test_main_model_answers_and_the_spare_is_not_asked(self) -> None:
        spare = Backend()

        assert chain(Backend(), spare).ask("ПРОМПТ", "привет").meta["backend"] == "claude_cli"
        assert spare.asked == 0

    def test_nothing_is_done_twice(self) -> None:
        """Лимит посреди фразы, а окно уже открыто: запасной открыл бы его снова."""
        spare = Backend()

        with pytest.raises(ModelUnavailable, match="already done in this phrase — page_open"):
            chain(Backend(ModelUnavailable("usage limit")), spare, actions=Actions("page_open")).ask("ПРОМПТ", "открой сайт")
        assert spare.asked == 0

    def test_other_failures_are_not_handed_over(self) -> None:
        """Не лимит, а ошибка — у запасного она повторилась бы или скрыла бы поломку."""
        spare = Backend()

        with pytest.raises(AgentBackendError, match="not JSON"):
            chain(Backend(AgentBackendError("not JSON")), spare).ask("ПРОМПТ", "привет")
        assert spare.asked == 0

    def test_every_backend_out_of_limit_is_the_last_failure(self) -> None:
        backends = (Backend(ModelUnavailable("claude limit")), Backend(ModelUnavailable("gemini 503")), Backend(ModelUnavailable("anthropic 529")))

        with pytest.raises(ModelUnavailable, match="anthropic 529"):
            chain(*backends).ask("ПРОМПТ", "привет")
        assert [backend.asked for backend in backends] == [1, 1, 1]


def call(tool: str, ok: bool = True, run: str = "r1") -> JournalEntry:
    return JournalEntry(datetime(2026, 10, 22, 19, 0), "tool", details={"tool": tool, "result": {"ok": ok}}, run=run)


class Journal:
    def __init__(self, *entries: JournalEntry) -> None:
        self._entries = list(entries)

    def tail(self, limit: int) -> list[JournalEntry]:
        return self._entries[-limit:]


class TestJournalRunActions:
    def test_only_successful_changing_calls_of_this_run(self) -> None:
        journal = Journal(
            call("page_click", run="r0"),               # прошлая фраза
            call("load_skill"),                         # только читает
            call("page_open"), call("page_open"),       # одна и та же ручка — один раз
            call("page_click", ok=False),               # отказ: ничего не сделано
            call("unknown_tool"),                       # риск неизвестен — считается меняющей
            JournalEntry(datetime(2026, 10, 22, 19, 0), "phrase", details={"tool": "page_write"}, run="r1"),
        )
        risks = {"load_skill": Risk.READ, "page_open": Risk.NAVIGATE, "page_click": Risk.EFFECT}

        assert JournalRunActions(journal, "r1", risks).done() == ("page_open", "unknown_tool")
