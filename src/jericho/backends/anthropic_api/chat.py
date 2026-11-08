"""Разговор с моделью через Anthropic Messages API."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from typing import Any, ClassVar, cast

import anthropic
from anthropic.types import (
    CacheControlEphemeralParam,
    ContentBlock,
    ContentBlockParam,
    ImageBlockParam,
    MessageParam,
    TextBlockParam,
    ToolParam,
    ToolResultBlockParam,
)

from jericho.backends.tool_loop.entities import CallAnswer, ModelTurn, ToolCall, ToolSpec, Usage
from jericho.backends.tool_loop.key import EnvironmentKey
from jericho.core.agent.protocols import AgentBackendError, ModelUnavailable


class AnthropicChat:
    """История сообщений в формате Messages API. Промпт и список ручек кешируются: от хода к ходу они те же."""

    _CACHE: ClassVar[CacheControlEphemeralParam] = {"type": "ephemeral"}
    # Лимит (429), перегрузка (529) и сбой на стороне API (5xx): другой бэкенд может справиться — `ModelUnavailable`.
    _UNAVAILABLE = (anthropic.RateLimitError, anthropic.OverloadedError, anthropic.ServiceUnavailableError, anthropic.InternalServerError)

    def __init__(self, client: anthropic.Anthropic, model: str, max_tokens: int, system_prompt: str, phrase: str, tools: Sequence[ToolSpec]) -> None:
        self._client = client
        self._model = model
        self._max_tokens = max_tokens
        self._system: list[TextBlockParam] = [{"type": "text", "text": system_prompt, "cache_control": self._CACHE}]
        self._tools: list[ToolParam] = [
            {"name": spec.name, "description": spec.description, "input_schema": dict(spec.schema)} for spec in tools
        ]
        if self._tools:
            self._tools[-1]["cache_control"] = self._CACHE
        self._messages: list[MessageParam] = [{"role": "user", "content": phrase}]

    def turn(self, timeout: float) -> ModelTurn:
        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                system=self._system,
                tools=self._tools,
                tool_choice={"type": "any"},          # ход — всегда вызов ручки; итог — вызов reply
                messages=self._messages,
                timeout=timeout,
            )
        except self._UNAVAILABLE as error:
            raise ModelUnavailable(f"Anthropic API: {error}") from error
        except anthropic.AnthropicError as error:
            raise AgentBackendError(f"Anthropic API: {error}") from error
        self._messages.append({"role": "assistant", "content": [self._echo(block) for block in response.content]})
        calls = tuple(self._call(block.id, block.name, block.input) for block in response.content if block.type == "tool_use")
        text = "".join(block.text for block in response.content if block.type == "text")
        usage = response.usage
        return ModelTurn(calls, text, Usage(usage.input_tokens, usage.output_tokens, usage.cache_read_input_tokens or 0))

    @staticmethod
    def _echo(block: ContentBlock) -> ContentBlockParam:
        """Ход модели — в историю как есть; только сломанный вход вызова — пустым объектом: иначе API отклонил бы
        следующий запрос, и модель не узнала бы, что вызов не выполнен."""
        echoed = block.model_dump(exclude_none=True, warnings=False)
        if block.type == "tool_use" and not isinstance(echoed.get("input"), dict):
            echoed["input"] = {}
        return cast(ContentBlockParam, echoed)

    @staticmethod
    def _call(call_id: str, name: str, arguments: object) -> ToolCall:
        """Вход — объект. `[]` иначе стал бы законным `{}` для ручки без полей, а число — падением (ревью П2 №5)."""
        if isinstance(arguments, dict):
            return ToolCall(call_id, name, cast(dict[str, object], arguments))
        return ToolCall(call_id, name, {}, "arguments must be a JSON object")

    def answer(self, answers: Sequence[CallAnswer]) -> None:
        results: list[ToolResultBlockParam] = [
            {"type": "tool_result", "tool_use_id": answer.call_id, "content": self._content(answer), "is_error": answer.is_error}
            for answer in answers
        ]
        self._messages.append({"role": "user", "content": results})

    @staticmethod
    def _content(answer: CallAnswer) -> str | list[TextBlockParam | ImageBlockParam]:
        """Текст ответа ручки и её картинки: модели Anthropic видят картинки прямо в ответе на вызов."""
        text = json.dumps(answer.content, ensure_ascii=False)
        if not answer.images:
            return text
        images: list[TextBlockParam | ImageBlockParam] = [
            {"type": "image", "source": {"type": "base64", "media_type": cast(Any, image.media_type), "data": image.base64}} for image in answer.images
        ]
        return [{"type": "text", "text": text}, *images]

    def remind(self, text: str) -> None:
        self._messages.append({"role": "user", "content": text})


class AnthropicModel:
    """Модель Anthropic по ключу. Клиент создаётся при первом поручении: без ключа ассистент всё равно собирается."""

    def __init__(self, model: str, max_tokens: int, key: EnvironmentKey, client: Callable[[str], anthropic.Anthropic] | None = None) -> None:
        self._model = model
        self._max_tokens = max_tokens
        self._key = key
        self._make_client = client or (lambda api_key: anthropic.Anthropic(api_key=api_key, max_retries=2))
        self._client: anthropic.Anthropic | None = None

    @property
    def name(self) -> str:
        return self._model

    def chat(self, system_prompt: str, phrase: str, tools: Sequence[ToolSpec]) -> AnthropicChat:
        if self._client is None:
            self._client = self._make_client(self._key.value())
        return AnthropicChat(self._client, self._model, self._max_tokens, system_prompt, phrase, tools)
