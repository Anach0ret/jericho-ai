"""Бэкенд «Anthropic API»: модель по ключу, цикл вызовов ведёт наш процесс."""

from __future__ import annotations

from jericho.backends.anthropic_api.chat import AnthropicModel
from jericho.backends.anthropic_api.settings import AnthropicSettings
from jericho.backends.tool_loop.base import ToolLoopBackend
from jericho.backends.tool_loop.key import EnvironmentKey
from jericho.backends.tool_loop.protocols import ChatModel


class AnthropicApi(ToolLoopBackend[AnthropicSettings]):
    name = "anthropic_api"
    settings_class = AnthropicSettings

    def model(self, settings: AnthropicSettings, key: EnvironmentKey) -> ChatModel:
        return AnthropicModel(settings.model, settings.max_tokens, key)
