"""Бэкенд «совместимый с OpenAI»: модель по адресу и ключу (или без ключа), цикл вызовов ведёт наш процесс."""

from __future__ import annotations

from jericho.backends.openai_api.chat import OpenAiModel
from jericho.backends.openai_api.settings import OpenAiSettings
from jericho.backends.tool_loop.base import ToolLoopBackend
from jericho.backends.tool_loop.key import EnvironmentKey
from jericho.backends.tool_loop.protocols import ChatModel


class OpenAiApi(ToolLoopBackend[OpenAiSettings]):
    name = "openai_api"
    settings_class = OpenAiSettings

    def model(self, settings: OpenAiSettings, key: EnvironmentKey) -> ChatModel:
        return OpenAiModel(settings.base_url, settings.model, settings.max_tokens, key, fallback=settings.fallback_models)
