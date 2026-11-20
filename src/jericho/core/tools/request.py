"""Параметры ручки — то, что приходит от модели, и схема, по которой модель их пишет."""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict

from jericho.core.schema import schema_for_model


class ToolRequest(BaseModel):
    """Основа запроса к ручке: поля с описаниями и ограничениями, лишних полей не принимает.

    Наследник объявляет поля через `Field(description=...)`; ограничения (`ge`, `le`, `Literal`) попадают
    в схему, и модель видит их до вызова. Проверка, которая касается нескольких полей, — `model_validator`.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    # Поля, которые в журнал вызова и в вопрос «да» каркаса не пишутся («скрыто: N знаков»), но личными данными
    # не считаются: фраза после них не «читала личное» (`Tool.private`), ручку может вызвать и запасная модель.
    # Так скрыто поручение `then` фоновой ручки — слова пользователя, а не чужая переписка (план 110, этап 3).
    masked: ClassVar[tuple[str, ...]] = ()

    @classmethod
    def tool_schema(cls) -> dict[str, Any]:
        """JSON-схема параметров в том виде, в каком её получает модель."""
        return schema_for_model(cls)
