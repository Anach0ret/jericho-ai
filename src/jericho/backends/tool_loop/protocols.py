"""Что общему циклу нужно от модели. Каждый бэкенд по ключу реализует это на своём SDK."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from jericho.backends.tool_loop.entities import CallAnswer, ModelTurn, ToolSpec


class Chat(Protocol):
    """Один разговор с моделью. Историю сообщений ведёт он: её формат у каждого API свой."""

    def turn(self, timeout: float) -> ModelTurn:
        """Следующий ход модели. Сбой сети, ключа или API — `AgentBackendError`."""
        ...

    def answer(self, answers: Sequence[CallAnswer]) -> None:
        """Ответы ручек на вызовы последнего хода, в том же порядке."""
        ...

    def remind(self, text: str) -> None:
        """Сообщение от каркаса вместо ответов ручек: модель ответила не так, как обязана."""
        ...


class ChatModel(Protocol):
    """Модель по ключу: начинает разговор с промптом, поручением и списком ручек."""

    @property
    def name(self) -> str: ...

    def chat(self, system_prompt: str, phrase: str, tools: Sequence[ToolSpec]) -> Chat: ...
