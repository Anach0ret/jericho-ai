"""Настоящий SDK Anthropic, подменена только сеть: видно, что уходит в API и как разбирается ответ."""

import json

import anthropic
import httpx2
import pytest

from jericho.backends.anthropic_api.chat import AnthropicModel
from jericho.backends.tool_loop.key import EnvironmentKey
from jericho.backends.tool_loop.loop import ToolLoop
from jericho.backends.tool_loop.testing import DONE, FRAME, Look, Open
from jericho.core.agent.forms import Brief
from jericho.core.agent.protocols import AgentBackendError
from jericho.core.tools.dispatcher import ToolDispatcher
from jericho.core.tools.middleware import Journal, Refusals


def message(*blocks: dict[str, object]) -> dict[str, object]:
    return {
        "id": "msg", "type": "message", "role": "assistant", "model": "claude-haiku-5-5", "content": list(blocks),
        "stop_reason": "tool_use", "stop_sequence": None,
        "usage": {"input_tokens": 1000, "output_tokens": 20, "cache_read_input_tokens": 900},
    }


def tool_use(id: str, name: str, arguments: object) -> dict[str, object]:
    return {"type": "tool_use", "id": id, "name": name, "input": arguments}


class Api:
    """Сеть, которая отвечает заранее заданными ответами и запоминает запросы."""

    def __init__(self, *responses: tuple[int, dict[str, object]]) -> None:
        self._responses = list(responses)
        self.requests: list[dict[str, object]] = []

    def client(self, api_key: str) -> anthropic.Anthropic:
        transport = httpx2.MockTransport(self._handle)
        return anthropic.Anthropic(api_key=api_key, max_retries=0, http_client=httpx2.Client(transport=transport))

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(json.loads(request.content))
        status, body = self._responses.pop(0)
        return httpx2.Response(status, json=body)


def loop(api: Api, environment: dict[str, str] | None = None) -> tuple[ToolLoop, Open]:
    key = EnvironmentKey("ANTHROPIC_API_KEY", {"ANTHROPIC_API_KEY": "sk-test"} if environment is None else environment)
    tool = Open()
    model = AnthropicModel("claude-haiku-5-5", 1024, key, client=api.client)
    return ToolLoop(model, [tool], ToolDispatcher([Journal, Refusals]), Brief().schema(), timeout=30, max_turns=5), tool


class TestAnthropicChat:
    def test_tool_images_reach_the_model_inside_the_tool_result(self) -> None:
        api = Api((200, message(tool_use("t1", "look", {"what": "видео"}))), (200, message(tool_use("t2", "reply", DONE))))
        model = AnthropicModel("claude-haiku-5-5", 1024, EnvironmentKey("ANTHROPIC_API_KEY", {"ANTHROPIC_API_KEY": "sk"}), client=api.client)
        ToolLoop(model, [Look()], ToolDispatcher([Journal, Refusals]), Brief().schema(), timeout=30, max_turns=5).ask("ПРОМПТ", "что на видео")

        [result] = api.requests[1]["messages"][-1]["content"]  # pyright: ignore[reportIndexIssue, reportGeneralTypeIssues]
        text, image = result["content"]
        assert json.loads(text["text"]) == {"ok": True, "frames": 1}
        assert image == {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": FRAME.base64}}

    def test_whole_loop_goes_through_the_real_sdk(self) -> None:
        api = Api((200, message(tool_use("t1", "open", {"what": "ютуб"}))), (200, message(tool_use("t2", "reply", DONE))))
        backend, tool = loop(api)

        answer = backend.ask("ПРОМПТ", "открой ютуб")

        assert answer.structured == DONE and tool.opened == ["ютуб"]
        assert answer.meta["cached_tokens"] == 1800
        first, second = api.requests
        assert first["tool_choice"] == {"type": "any"}
        assert first["system"] == [{"type": "text", "text": "ПРОМПТ", "cache_control": {"type": "ephemeral"}}]
        assert [tool["name"] for tool in first["tools"]] == ["open", "reply"]   # pyright: ignore[reportIndexIssue, reportGeneralTypeIssues]
        result = second["messages"][-1]["content"][0]   # pyright: ignore[reportIndexIssue]
        assert result["tool_use_id"] == "t1" and json.loads(result["content"]) == {"ok": True, "opened": "ютуб"}

    @pytest.mark.parametrize("arguments", [[], 42, None, "текст"])
    def test_input_that_is_not_an_object_is_not_run(self, arguments: object) -> None:
        """`[]` становился `{}` и выполнял ручку без полей, число и null роняли фразу `TypeError` (ревью П2 №5)."""
        api = Api((200, message(tool_use("t1", "open", arguments))), (200, message(tool_use("t2", "reply", DONE))))
        backend, tool = loop(api)

        answer = backend.ask("ПРОМПТ", "открой ютуб")

        result = api.requests[1]["messages"][-1]["content"][0]   # pyright: ignore[reportIndexIssue]
        echoed = api.requests[1]["messages"][-2]["content"][0]   # pyright: ignore[reportIndexIssue]
        assert answer.structured == DONE and tool.opened == [] and echoed["input"] == {}
        assert result["is_error"] is True and json.loads(result["content"])["error"] == "invalid_arguments"

    def test_api_error_becomes_a_backend_error(self) -> None:
        api = Api((401, {"type": "error", "error": {"type": "authentication_error", "message": "invalid x-api-key"}}))

        with pytest.raises(AgentBackendError, match="Anthropic API"):
            loop(api)[0].ask("ПРОМПТ", "привет")

    def test_without_the_key_the_assistant_says_where_to_put_it(self) -> None:
        with pytest.raises(AgentBackendError, match="ANTHROPIC_API_KEY"):
            loop(Api(), environment={})[0].ask("ПРОМПТ", "привет")
