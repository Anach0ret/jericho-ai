import subprocess
import sys
from collections.abc import Mapping, Sequence
from typing import Self

import pytest

from jericho.backends.tool_loop.entities import CallAnswer, ModelTurn, ToolCall, ToolSpec, Usage
from jericho.backends.tool_loop.loop import ToolLoop
from jericho.backends.tool_loop.testing import DONE, Open, OpenRequest
from jericho.core.agent.forms import Brief
from jericho.core.agent.protocols import AgentBackendError
from jericho.core.tools.dispatcher import ToolDispatcher
from jericho.core.tools.middleware import Journal, Refusals
from jericho.core.tools.result import ToolResult


class Model:
    """Модель, чьи ходы известны заранее; запоминает, что ей вернули."""

    name = "fake"

    def __init__(self, *turns: ModelTurn) -> None:
        self._turns = list(turns)
        self.answers: list[list[CallAnswer]] = []
        self.reminders: list[str] = []
        self.tools: list[str] = []

    def chat(self, system_prompt: str, phrase: str, tools: Sequence[ToolSpec]) -> Self:
        self.tools = [spec.name for spec in tools]
        return self

    def turn(self, timeout: float) -> ModelTurn:
        return self._turns.pop(0)

    def answer(self, answers: Sequence[CallAnswer]) -> None:
        self.answers.append(list(answers))

    def remind(self, text: str) -> None:
        self.reminders.append(text)


def calls(*pairs: tuple[str, dict[str, object]]) -> ModelTurn:
    return ModelTurn(tuple(ToolCall(f"c{n}", name, arguments) for n, (name, arguments) in enumerate(pairs)), usage=Usage(100, 10))


def loop(model: Model, tool: Open, max_turns: int = 5) -> ToolLoop:
    return ToolLoop(model, [tool], ToolDispatcher([Journal, Refusals]), Brief().schema(), timeout=30, max_turns=max_turns)


class TestToolLoop:
    def test_tools_run_through_the_dispatcher_until_the_model_replies(self) -> None:
        tool, model = Open(), Model(calls(("open", {"what": "ютуб"})), calls(("reply", DONE)))

        answer = loop(model, tool).ask("промпт", "открой ютуб")

        assert tool.opened == ["ютуб"] and answer.structured == DONE
        assert model.tools == ["open", "reply"]
        assert answer.meta["num_turns"] == 2 and answer.meta["input_tokens"] == 200
        assert answer.meta["calls"] == [{"tool": "open", "ok": True}]

    def test_refusal_reaches_the_model_as_an_error(self) -> None:
        model = Model(calls(("open", {"what": ""})), calls(("reply", DONE)))

        loop(model, Open()).ask("промпт", "открой")

        assert model.answers[0][0].is_error and model.answers[0][0].content["error"] == "empty"

    def test_reply_next_to_an_action_is_not_accepted(self) -> None:
        """Ответ, написанный до того, как стало известно, что сделала ручка, — не ответ."""
        tool = Open()
        model = Model(calls(("open", {"what": "ютуб"}), ("reply", DONE)), calls(("reply", DONE)))

        answer = loop(model, tool).ask("промпт", "открой ютуб")

        assert [a.content.get("error") for a in model.answers[0]] == [None, ToolLoop.REPLY_TOO_EARLY]
        assert answer.meta["num_turns"] == 2 and tool.opened == ["ютуб"]

    def test_text_without_calls_is_answered_with_a_reminder(self) -> None:
        model = Model(ModelTurn(text="Готово!"), calls(("reply", DONE)))

        assert loop(model, Open()).ask("промпт", "привет").structured == DONE
        assert model.reminders == [ToolLoop.NO_CALL]

    def test_reply_written_as_text_is_taken(self) -> None:
        """Слабые модели (Ollama) не всегда слушаются требования вызвать ручку, но форму ответа соблюдают."""
        answer = loop(Model(ModelTurn(text='```json\n{"status": "done", "message": "Открыл"}\n```')), Open()).ask("промпт", "привет")

        assert answer.structured == DONE and answer.meta["reply_as_text"] is True

    def test_unknown_tool_is_named_back(self) -> None:
        model = Model(calls(("shell", {})), calls(("reply", DONE)))

        loop(model, Open()).ask("промпт", "сделай")

        assert model.answers[0][0].content["error"] == ToolLoop.UNKNOWN_TOOL

    def test_endless_calls_end_with_a_failure(self) -> None:
        model = Model(*(calls(("open", {"what": "ютуб"})) for _ in range(3)))

        with pytest.raises(AgentBackendError, match="did not reply in 3 turns"):
            loop(model, Open(), max_turns=3).ask("промпт", "открой")

    def test_tool_cannot_take_the_name_of_the_final_answer(self) -> None:
        class Reply(Open):
            name = "reply"

        with pytest.raises(ValueError, match="reserved"):
            loop(Model(), Reply())


def strict(model: Model, tool: Open) -> ToolLoop:
    """Цикл с формой ответа проекта: не по форме — ValueError, как у настоящей формы."""
    return ToolLoop(
        model, [tool], ToolDispatcher([Journal, Refusals]), Brief().schema(), timeout=30, max_turns=5, check_reply=Brief().parse,
    )


class TestSecondChance:
    def test_reply_not_by_the_form_gets_one_more_try(self) -> None:
        model = Model(calls(("reply", {"status": "готово"})), calls(("reply", DONE)))

        answer = strict(model, Open()).ask("промпт", "открой")

        assert answer.structured == DONE and answer.meta["reply_retried"] is True
        assert model.answers[0][0].content["error"] == ToolLoop.REPLY_INVALID

    def test_second_try_is_for_words_not_for_deeds(self) -> None:
        tool = Open()
        model = Model(calls(("reply", {"status": "готово"})), calls(("open", {"what": "ютуб"})), calls(("reply", DONE)))

        strict(model, tool).ask("промпт", "открой")

        assert tool.opened == [] and model.answers[1][0].content["error"] == ToolLoop.REPLY_ONLY

    def test_only_one_second_try(self) -> None:
        bad: dict[str, object] = {"status": "готово"}
        answer = strict(Model(calls(("reply", bad)), calls(("reply", bad))), Open()).ask("промпт", "открой")

        assert answer.structured == bad      # дальше его не примет форма ответа: поручение получит failed


class TestOwnQuestion:
    def test_model_cannot_confirm_its_own_question_within_one_loop(self) -> None:
        """У бэкенда по ключу нет отдельного процесса ручек: весь цикл — один запуск, и «да» на свой вопрос не принимается."""
        from jericho.backends.tool_loop.testing import Send
        from jericho.core import ConfirmationGate
        from jericho.core.testing.fakes import Confirmations
        from jericho.core.tools.confirm import Confirm
        from jericho.core.tools.policy import RiskPolicy
        from jericho.core.tools.session import CallSession

        store, session = Confirmations(), CallSession()
        gate = ConfirmationGate(store, "one-run")
        dispatcher = ToolDispatcher([Journal, Refusals], session, policy=RiskPolicy(gate))
        send = Send()
        model = Model(calls(("send", {"what": "письмо"})), calls(("confirm", {})), calls(("reply", DONE)))
        backend = ToolLoop(model, [send, Confirm(gate, dispatcher, [send], session)], dispatcher, Brief().schema(), timeout=30, max_turns=5)

        backend.ask("промпт", "отправь")

        assert [answer[0].content.get("error") for answer in model.answers] == ["needs_confirm", "nothing_to_confirm"]
        assert send.opened == []


class TestBudget:
    """Ревью R08: срок поручения проверяется перед каждой ручкой, а не только перед ходом модели."""

    def test_tool_does_not_start_after_the_phrase_ran_out_of_time(self) -> None:
        now = [0.0]

        class Slow(Open):
            def _run(self, request: OpenRequest) -> ToolResult:
                now[0] += 40      # ручка шла 40 секунд
                return super()._run(request)

        tool = Slow()
        model = Model(calls(("open", {"what": "a"}), ("open", {"what": "b"})), calls(("reply", DONE)))
        backend = ToolLoop(model, [tool], ToolDispatcher([Journal, Refusals]), Brief().schema(), timeout=30, max_turns=5, clock=lambda: now[0])

        with pytest.raises(AgentBackendError):
            backend.ask("промпт", "открой оба")

        assert tool.opened == ["a"] and model.answers[0][1].content["error"] == ToolLoop.OUT_OF_TIME

    def test_number_of_calls_is_limited_even_within_one_turn(self) -> None:
        tool = Open()
        five: list[tuple[str, dict[str, object]]] = [("open", {"what": str(n)}) for n in range(5)]
        model = Model(calls(*five), calls(("reply", DONE)))
        backend = ToolLoop(model, [tool], ToolDispatcher([Journal, Refusals]), Brief().schema(), timeout=30, max_turns=5, max_calls=3)

        backend.ask("промпт", "открой пять")

        assert len(tool.opened) == 3 and model.answers[0][-1].content["error"] == ToolLoop.TOO_MANY_CALLS


def test_call_with_broken_arguments_is_not_executed() -> None:
    """Ревью R09: сломанные параметры — не «пустые»: `{}` для ручки без обязательных полей — законный вызов."""
    tool = Open()
    model = Model(ModelTurn((ToolCall("c0", "open", {}, problem="arguments are not valid JSON"),)), calls(("reply", DONE)))

    loop(model, tool).ask("промпт", "открой")

    assert model.answers[0][0].content["error"] == ToolLoop.INVALID_ARGUMENTS and tool.opened == []


def written(text: str) -> Mapping[str, object] | None:
    """Что цикл принял за ответ, написанный текстом; None — не принял и напомнил вызвать reply."""
    answer = loop(Model(ModelTurn(text=text), calls(("reply", DONE))), Open()).ask("промпт", "привет")
    return answer.structured if answer.meta.get("reply_as_text") else None


class TestReplyWrittenAsText:
    """Ограда ```json вокруг ответа текстом: какие варианты принимаются, а какой текст JSON не считается."""

    @pytest.mark.parametrize("text", [
        '{"status": "done", "message": "Открыл"}',
        '  {"status": "done", "message": "Открыл"}\n',
        '```json\n{"status": "done", "message": "Открыл"}\n```',
        '```\n{"status": "done", "message": "Открыл"}\n```',
        '```json{"status": "done", "message": "Открыл"}```',
        '```json   \n\n {"status": "done", "message": "Открыл"} \n\n ```',
        '\n```json\n{"status": "done", "message": "Открыл"}\n```\n',
        '```json\n {"status": "done", "message": "Открыл"} \n```',
    ])
    def test_object_bare_or_fenced_is_taken(self, text: str) -> None:
        assert written(text) == DONE

    @pytest.mark.parametrize("text", [
        "Готово!",
        "``````",
        "```json\n```",
        '```json\n{"status": "done", "message": "Открыл"}',
        '{"status": "done", "message": "Открыл"}\n```',
        'Вот ответ: ```json\n{"status": "done", "message": "Открыл"}\n```',
        '```json\n{"status": "done", "message": "Открыл"}\n``` и ещё слово',
        '```JSON\n{"status": "done", "message": "Открыл"}\n```',
        '```python\n{"status": "done", "message": "Открыл"}\n```',
        '```json\n["done"]\n```',
        "```json\n" + " " * 50 + "x",
    ])
    def test_anything_else_is_not_taken_for_a_reply(self, text: str) -> None:
        assert written(text) is None

    def test_unclosed_fence_with_long_whitespace_is_parsed_in_linear_time(self) -> None:
        """Sonar S8786: прежняя регулярка на незакрытой ограде росла взрывно (4000 пробелов — 49 с у Codex).

        Проба — в отдельном процессе с конечным сроком: зависание не вешает основной прогон тестов.
        """
        probe = (
            "from jericho.backends.tool_loop.tests.test_loop import written\n"
            "assert written('```json\\n' + ' ' * 200_000 + 'x') is None\n"
        )
        subprocess.run([sys.executable, "-c", probe], check=True, timeout=20)
