"""Понятия модуля: реплика разговора."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import ClassVar

from jericho.core.agent.entities import AgentReply, ReplyStatus


@dataclass(frozen=True, slots=True)
class Exchange:
    """Одна пара «фраза → ответ»."""

    time: datetime
    phrase: str
    status: ReplyStatus
    message: str
    foreign: tuple[str, ...] = ()     # чей чужой текст модель читала в этой фразе: он мог попасть в ответ
    body: str = ""                    # подробности отчёта (форма «report»), сокращённые; у короткой формы пусто

    BODY_LIMIT: ClassVar[int] = 800

    @classmethod
    def of(cls, time: datetime, phrase: str, reply: AgentReply, foreign: tuple[str, ...] = ()) -> Exchange:
        """Обмен из ответа: текст отчёта — вместе с заголовком. Журнал 02.11.2026: на «что из этого уже есть?» модель
        видела только заголовок прошлого отчёта, а не список мер в нём."""
        body = reply.body if len(reply.body) <= cls.BODY_LIMIT else f"{reply.body[: cls.BODY_LIMIT]}…"
        return cls(time, phrase, reply.status, reply.message, foreign, body)

    @property
    def said(self) -> str:
        """Что ответил ассистент — заголовок и подробности одной строкой."""
        return f"{self.message} — {' '.join(self.body.split())}" if self.body else self.message
