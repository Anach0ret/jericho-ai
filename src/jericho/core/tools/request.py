"""Параметры ручки — то, что приходит от модели, и схема, по которой модель их пишет."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from jericho.core.schema import schema_for_model


class ToolRequest(BaseModel):
    """Основа запроса к ручке: поля с описаниями и ограничениями, лишних полей не принимает.

    Наследник объявляет поля через `Field(description=...)`; ограничения (`ge`, `le`, `Literal`) попадают
    в схему, и модель видит их до вызова. Проверка, которая касается нескольких полей, — `model_validator`.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    @classmethod
    def tool_schema(cls) -> dict[str, Any]:
        """JSON-схема параметров в том виде, в каком её получает модель."""
        return schema_for_model(cls)
