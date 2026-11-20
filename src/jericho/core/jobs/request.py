"""Параметры фоновой ручки: поле `then` — одно описание на каркас, у всех ручек, которые запускают работу."""

from __future__ import annotations

from typing import ClassVar

from pydantic import Field

from jericho.core.tools.request import ToolRequest


class BackgroundRequest(ToolRequest):
    """Основа запроса ручки, которая запускает фоновую работу (`JobLauncher`): «скачай и пришли другу».

    Текст `then` скрыт в журнале вызова (`masked`): там — «скрыто: N знаков» и id продолжения из ответа.
    """

    masked: ClassVar[tuple[str, ...]] = ("then",)

    then: str = Field(
        default="", max_length=500,
        description=(
            "Второй шаг, когда работа удастся, — словами пользователя: «скачай и пришли другу» → "
            "then=\"пришли скачанный файл другу\". Выполнится сам, с итогом работы. "
            "Второго шага не просили — не указывай; сейчас второй шаг не делай."
        ),
    )
