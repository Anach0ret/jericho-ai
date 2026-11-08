"""Настройки бэкенда «Anthropic API» — раздел `anthropic_api`."""

from __future__ import annotations

from jericho.backends.tool_loop.settings import ApiModelSettings


class AnthropicSettings(ApiModelSettings):
    """Проект объявляет раздел у себя: `anthropic_api: AnthropicSettings = AnthropicSettings(model="claude-haiku-5-5")`."""

    model: str = "claude-haiku-5-5"
    api_key_env: str = "ANTHROPIC_API_KEY"
