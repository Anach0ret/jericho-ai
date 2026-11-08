"""Настройки бэкенда «совместимый с OpenAI» — раздел `openai_api`."""

from __future__ import annotations

from jericho.backends.tool_loop.settings import ApiModelSettings


class OpenAiSettings(ApiModelSettings):
    """Любой адрес с протоколом OpenAI: сам OpenAI, OpenRouter, Ollama на этой машине.

    Проект объявляет раздел у себя: `openai_api: OpenAiSettings = OpenAiSettings(base_url=..., model=...)`.
    Пустая модель — поручение отвечает сбоем; пустое имя переменной с ключом — ключ не нужен (Ollama).
    """

    base_url: str = "http://localhost:11434/v1"      # по умолчанию — Ollama на этой машине
    # Запасные модели того же адреса: основная ответила «лимит исчерпан» (HTTP 429) или «перегружена» (HTTP 5xx) —
    # ход повторяется на следующей.
    # Нужны бесплатным уровням (Gemini, OpenRouter): одна фраза — это несколько запросов, по одному на ход.
    fallback_models: tuple[str, ...] = ()
