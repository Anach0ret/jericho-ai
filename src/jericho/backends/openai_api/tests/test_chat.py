"""Настоящий SDK OpenAI, подменена только сеть."""

import json

import httpx2
import openai
import pytest

from jericho.backends.openai_api import chat as chat_module
from jericho.backends.openai_api.chat import OpenAiModel
from jericho.backends.tool_loop.key import EnvironmentKey
from jericho.backends.tool_loop.loop import ToolLoop
from jericho.backends.tool_loop.testing import DONE, Look, Open
from jericho.core.agent.forms import Brief
from jericho.core.agent.protocols import AgentBackendError, ModelTimeout
from jericho.core.tools.dispatcher import ToolDispatcher
from jericho.core.tools.middleware import Journal, Refusals


def completion(*calls: tuple[str, str, str]) -> dict[str, object]:
    tool_calls = [{"id": id, "type": "function", "function": {"name": name, "arguments": arguments}} for id, name, arguments in calls]
    return {
        "id": "c", "object": "chat.completion", "created": 0, "model": "qwen3",
        "choices": [{"index": 0, "finish_reason": "tool_calls", "message": {"role": "assistant", "content": None, "tool_calls": tool_calls}}],
        "usage": {"prompt_tokens": 500, "completion_tokens": 15, "total_tokens": 515},
    }


class Api:
    def __init__(self, *responses: dict[str, object] | int) -> None:
        """Ответ — тело при успехе или код ошибки HTTP: 429 — «лимит исчерпан»."""
        self._responses = list(responses)
        self.requests: list[dict[str, object]] = []
        self.keys: list[str] = []

    def client(self, api_key: str) -> openai.OpenAI:
        self.keys.append(api_key)
        transport = httpx2.MockTransport(self._handle)
        return openai.OpenAI(base_url="http://localhost:11434/v1", api_key=api_key, max_retries=0, http_client=httpx2.Client(transport=transport))

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(json.loads(request.content))
        response = self._responses.pop(0)
        if isinstance(response, int):
            return httpx2.Response(response, json={"error": {"message": "quota exceeded", "code": response}})
        return httpx2.Response(200, json=response)


def loop(api: Api, model: str = "qwen3", fallback: tuple[str, ...] = ()) -> tuple[ToolLoop, Open]:
    tool = Open()
    chat_model = OpenAiModel("http://localhost:11434/v1", model, 1024, EnvironmentKey("", {}), client=api.client, fallback=fallback)
    return ToolLoop(chat_model, [tool], ToolDispatcher([Journal, Refusals]), Brief().schema(), timeout=30, max_turns=5), tool


class TestOpenAiChat:
    def test_model_learns_it_did_not_see_the_images(self) -> None:
        """Протокол OpenAI не несёт картинок в ответе ручки: пусть модель знает это и не выдумывает, что на них."""
        api = Api(completion(("a", "look", '{"what": "видео"}')), completion(("b", "reply", json.dumps(DONE))))
        model = OpenAiModel("http://localhost:11434/v1", "qwen3", 1024, EnvironmentKey("", {}), client=api.client)
        ToolLoop(model, [Look()], ToolDispatcher([Journal, Refusals]), Brief().schema(), timeout=30, max_turns=5).ask("ПРОМПТ", "что на видео")

        answer = api.requests[1]["messages"][-1]  # pyright: ignore[reportIndexIssue]
        assert json.loads(answer["content"]) == {"ok": True, "frames": 1, "images_not_shown": 1}  # pyright: ignore[reportIndexIssue, reportArgumentType]

    def test_whole_loop_goes_through_the_real_sdk(self) -> None:
        api = Api(completion(("a", "open", '{"what": "ютуб"}')), completion(("b", "reply", json.dumps(DONE))))
        backend, tool = loop(api)

        answer = backend.ask("ПРОМПТ", "открой ютуб")

        assert answer.structured == DONE and tool.opened == ["ютуб"]
        assert api.keys == [OpenAiModel.NO_KEY]       # адрес без ключа: Ollama
        first, second = api.requests
        assert first["tool_choice"] == "required" and first["messages"][0] == {"role": "system", "content": "ПРОМПТ"}  # pyright: ignore[reportIndexIssue]
        assert second["messages"][-1]["tool_call_id"] == "a"  # pyright: ignore[reportIndexIssue]

    def test_arguments_that_are_not_json_never_reach_the_tool(self) -> None:
        api = Api(completion(("a", "open", "{не json")), completion(("b", "reply", json.dumps(DONE))))
        backend, tool = loop(api)

        backend.ask("ПРОМПТ", "открой")

        assert json.loads(api.requests[1]["messages"][-1]["content"])["error"] == "invalid_arguments"  # pyright: ignore[reportIndexIssue]
        assert tool.opened == []

    def test_model_must_be_named(self) -> None:
        with pytest.raises(AgentBackendError, match="openai_api.model"):
            loop(Api(), model="")[0].ask("ПРОМПТ", "привет")

    def test_rate_limited_model_hands_the_same_turn_to_the_next(self) -> None:
        """Бесплатный уровень: одна фраза — несколько запросов; лимит основной модели не обрывает поручение."""
        api = Api(429, completion(("a", "open", '{"what": "ютуб"}')), completion(("b", "reply", json.dumps(DONE))))
        backend, tool = loop(api, model="flash-lite", fallback=("flash",))

        assert backend.ask("ПРОМПТ", "открой ютуб").structured == DONE and tool.opened == ["ютуб"]
        assert [request["model"] for request in api.requests] == ["flash-lite", "flash", "flash"]   # дальше — на запасной

    def test_overloaded_model_hands_the_turn_to_the_next(self) -> None:
        """Gemini «high demand» — HTTP 503: поручение не обрывается, пока есть запасная модель."""
        api = Api(503, completion(("b", "reply", json.dumps(DONE))))
        backend, _ = loop(api, model="flash-lite", fallback=("flash",))

        assert backend.ask("ПРОМПТ", "что с сервером?").structured == DONE
        assert [request["model"] for request in api.requests] == ["flash-lite", "flash"]

    def test_last_model_overloaded_is_a_backend_error(self) -> None:
        backend, _ = loop(Api(503, 503), model="flash-lite", fallback=("flash",))

        with pytest.raises(AgentBackendError, match="unavailable of flash"):
            backend.ask("ПРОМПТ", "что с сервером?")

    def test_bad_request_is_not_hidden_by_the_fallback(self) -> None:
        """400 — ошибка запроса, а не модели: на другой модели она повторится, переключаться незачем."""
        api = Api(400)
        backend, _ = loop(api, model="flash-lite", fallback=("flash",))

        with pytest.raises(AgentBackendError):
            backend.ask("ПРОМПТ", "привет")
        assert len(api.requests) == 1

    def test_last_model_out_of_limit_is_a_backend_error(self) -> None:
        backend, _ = loop(Api(429, 429), model="flash-lite", fallback=("flash",))

        with pytest.raises(AgentBackendError, match="rate limit of flash"):
            backend.ask("ПРОМПТ", "открой")


class TestModelsShareTheTime:
    def test_next_model_gets_what_is_left_not_the_whole_time(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Ревью 02.11.2026, сводка №9: перебор моделей отдавал каждой весь исходный срок."""
        now = [0.0]
        monkeypatch.setattr(chat_module.time, "monotonic", lambda: now[0])

        class SlowApi(Api):
            def _handle(self, request: httpx2.Request) -> httpx2.Response:
                now[0] += 40      # первая модель думала 40 с из 30 и упёрлась в лимит
                return super()._handle(request)

        api = SlowApi(429, completion(("b", "reply", json.dumps(DONE))))
        backend, _ = loop(api, model="flash-lite", fallback=("flash",))

        with pytest.raises(ModelTimeout):
            backend.ask("ПРОМПТ", "открой")
        assert len(api.requests) == 1      # вторая модель не спрошена: времени нет
