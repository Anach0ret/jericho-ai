"""Ответ модели на фразу — граница, где данные приходят снаружи."""

from __future__ import annotations

import json
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from jericho.core.agent.entities import AgentReply, ReplyStatus
from jericho.core.schema import schema_for_model


class ModelReply(BaseModel):
    """То, что модели разрешено сказать. Статуса `failed` здесь нет: его ставит только сам Jericho."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["done", "clarify", "refused", "ignored"]
    message: str
    # Варианты ответа на вопрос `clarify` — станут кнопками: «Петров», «Смирнов». Без вопроса — пусто.
    options: list[Annotated[str, StringConstraints(min_length=1, max_length=40)]] = Field(default_factory=list, max_length=4)

    @field_validator("message")
    @classmethod
    def _unwrap(cls, message: str) -> str:
        """Модель иногда кладёт весь ответ ещё раз внутрь `message` — тогда берём текст из вложенного."""
        if not message.lstrip().startswith("{"):
            return message
        try:
            nested = json.loads(message)
        except ValueError:
            return message
        inner = nested.get("message") if isinstance(nested, dict) else None
        return inner if isinstance(inner, str) else message

    @classmethod
    def json_schema(cls) -> dict[str, Any]:
        """Схема, которой модель обязана следовать (структурированный вывод)."""
        return schema_for_model(cls)

    def to_reply(self) -> AgentReply:
        options = tuple(self.options) if self.status == "clarify" else ()
        return AgentReply(ReplyStatus(self.status), self.message, options=options)
