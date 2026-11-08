"""Протоколы модуля: где хранится недавний разговор."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from jericho.core.agent.entities import AgentReply
from jericho.modules.dialogue.entities import Exchange


class ConversationMemory(Protocol):
    """Короткая память разговора: чтобы на вопрос Jericho можно было ответить следующей фразой."""

    def recent(self) -> tuple[Exchange, ...]:
        """Недавние реплики, от старых к новым. Устаревшие не возвращаются."""
        ...

    def remember(self, phrase: str, reply: AgentReply, foreign: Sequence[str] = ()) -> None: ...
