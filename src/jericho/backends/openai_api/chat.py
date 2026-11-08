"""Разговор с моделью через Chat Completions API — протокол OpenAI, который понимают многие адреса."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Mapping, Sequence
from typing import cast

import openai
from openai.types.chat import ChatCompletion, ChatCompletionFunctionToolParam, ChatCompletionMessageParam

from jericho.backends.tool_loop.entities import CallAnswer, ModelTurn, ToolCall, ToolSpec, Usage
from jericho.backends.tool_loop.key import EnvironmentKey
from jericho.core.agent.protocols import AgentBackendError, ModelTimeout, ModelUnavailable

logger = logging.getLogger(__name__)


def parse_arguments(raw: str | None) -> tuple[Mapping[str, object], str]:
    """Параметры приходят строкой JSON. Не JSON-объект — не «пустые параметры», а ошибка: `{}` для `confirm()`
    и для ручки без обязательных полей — законный вызов, и сломанный протокол выполнил бы действие (ревью R09)."""
    if raw is None or not raw.strip():
        return {}, ""          # параметров нет вовсе — так модель вызывает ручку без параметров
    try:
        parsed = json.loads(raw)
    except ValueError:
        return {}, "arguments are not valid JSON"
    if not isinstance(parsed, dict):
        return {}, "arguments must be a JSON object"
    return parsed, ""


class OpenAiChat:
    """История сообщений в формате Chat Completions. Модель упёрлась в лимит — разговор продолжает следующая из списка."""

    def __init__(
        self, client: openai.OpenAI, models: Sequence[str], max_tokens: int, system_prompt: str, phrase: str, tools: Sequence[ToolSpec]
    ) -> None:
        self._client = client
        self._models = list(models)      # первая — та, что отвечает сейчас
        self._max_tokens = max_tokens
        self._tools: list[ChatCompletionFunctionToolParam] = [
            {"type": "function", "function": {"name": spec.name, "description": spec.description, "parameters": dict(spec.schema)}}
            for spec in tools
        ]
        self._messages: list[ChatCompletionMessageParam] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": phrase},
        ]

    def turn(self, timeout: float) -> ModelTurn:
        response = self._create(timeout)
        if not response.choices:
            raise AgentBackendError("OpenAI-compatible API: answer without choices")
        message = response.choices[0].message
        self._messages.append(cast(ChatCompletionMessageParam, message.model_dump(exclude_none=True)))
        calls = tuple(
            ToolCall(call.id, call.function.name, *parse_arguments(call.function.arguments))
            for call in message.tool_calls or ()
            if call.type == "function"
        )
        usage = response.usage
        cached = (usage.prompt_tokens_details.cached_tokens or 0) if usage and usage.prompt_tokens_details else 0
        counted = Usage(usage.prompt_tokens, usage.completion_tokens, cached) if usage else Usage()
        return ModelTurn(calls, message.content or "", counted)

    def _create(self, timeout: float) -> ChatCompletion:
        """Следующая модель получает то, что осталось от `timeout`, а не весь заново (ревью 02.11.2026, сводка №9)."""
        until = time.monotonic() + timeout
        while True:
            left = until - time.monotonic()
            if left <= 0:
                raise ModelTimeout(f"OpenAI-compatible API: no time left to ask {self._models[0]}")
            try:
                return self._client.chat.completions.create(
                    model=self._models[0],
                    max_tokens=self._max_tokens,
                    messages=self._messages,
                    tools=self._tools,
                    tool_choice="required",                # ход — всегда вызов ручки; итог — вызов reply
                    timeout=left,
                )
            except (openai.RateLimitError, openai.InternalServerError) as error:
                # 429 — лимит этой модели, 5xx — модель перегружена или упала («high demand»): у другой модели того же
                # адреса свой лимит и своя нагрузка. Повторы одной модели SDK уже сделал сам (max_retries).
                reason = "rate limit" if isinstance(error, openai.RateLimitError) else "unavailable"
                if len(self._models) == 1:
                    raise ModelUnavailable(f"OpenAI-compatible API: {reason} of {self._models[0]}: {error}") from error
                logger.warning(
                    "model_switched", extra={"data": {"model": self._models[0], "next": self._models[1], "status": error.status_code}}
                )
                self._models.pop(0)
            except openai.OpenAIError as error:
                raise AgentBackendError(f"OpenAI-compatible API: {error}") from error

    def answer(self, answers: Sequence[CallAnswer]) -> None:
        for answer in answers:
            # В ответе на вызов по протоколу OpenAI картинок нет — модель узнаёт, что их не видела, и не выдумывает.
            content = {**answer.content, "images_not_shown": len(answer.images)} if answer.images else answer.content
            self._messages.append({"role": "tool", "tool_call_id": answer.call_id, "content": json.dumps(content, ensure_ascii=False)})

    def remind(self, text: str) -> None:
        self._messages.append({"role": "user", "content": text})


class OpenAiModel:
    """Модель по адресу с протоколом OpenAI. Клиент создаётся при первом поручении."""

    NO_KEY = "not-needed"     # SDK требует ключ всегда; адресу без ключа (Ollama) всё равно, что в нём

    def __init__(
        self, base_url: str, model: str, max_tokens: int, key: EnvironmentKey,
        client: Callable[[str], openai.OpenAI] | None = None, fallback: Sequence[str] = (),
    ) -> None:
        self._base_url = base_url
        self._model = model
        self._fallback = tuple(fallback)
        self._max_tokens = max_tokens
        self._key = key
        self._make_client = client or (lambda api_key: openai.OpenAI(base_url=self._base_url, api_key=api_key, max_retries=2))
        self._client: openai.OpenAI | None = None

    @property
    def name(self) -> str:
        return self._model

    def chat(self, system_prompt: str, phrase: str, tools: Sequence[ToolSpec]) -> OpenAiChat:
        if not self._model:
            raise AgentBackendError("openai_api.model is not set: name the model in the settings")
        if self._client is None:
            self._client = self._make_client(self._key.value() or self.NO_KEY)
        return OpenAiChat(self._client, (self._model, *self._fallback), self._max_tokens, system_prompt, phrase, tools)
