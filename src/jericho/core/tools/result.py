"""Ответ инструмента — то, что получает модель после вызова."""

from __future__ import annotations

import base64
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace


class ToolRefusal(Exception):
    """Инструмент не будет выполнять запрос: неверный параметр, цель не найдена, нужно подтверждение.

    Шаг, который не может продолжать, бросает отказ — и сценарий читается сверху вниз без проверок
    после каждой строки. В ответ модели отказ превращает слой `Refusals`.
    """

    def __init__(self, code: str, **details: object) -> None:
        super().__init__(code)
        self.code = code
        self.details = details


@dataclass(frozen=True, slots=True)
class ToolImage:
    """Картинка в ответе ручки — кадр видео, фото. Модель её видит, в журнал она не попадает."""

    data: bytes
    media_type: str = "image/jpeg"

    @property
    def base64(self) -> str:
        return base64.b64encode(self.data).decode("ascii")


@dataclass(frozen=True, slots=True)
class ToolResult:
    """Итог вызова: получилось или нет, и подробности.

    `error` — короткий код причины (project_not_found, project_ambiguous, …), по которому
    модель решает, что сказать пользователю.
    """

    ok: bool
    error: str = ""
    data: Mapping[str, object] = field(default_factory=dict)
    images: tuple[ToolImage, ...] = ()     # не в `to_dict`: журнал и текст ответа — без картинок

    @classmethod
    def success(cls, **data: object) -> ToolResult:
        return cls(ok=True, data=data)

    @classmethod
    def failure(cls, error: str, **data: object) -> ToolResult:
        return cls(ok=False, error=error, data=data)

    def showing(self, images: Sequence[ToolImage]) -> ToolResult:
        """Тот же ответ с картинками для модели: `ToolResult.success(...).showing(frames)`."""
        return replace(self, images=tuple(images))

    def to_dict(self) -> dict[str, object]:
        """Вид, в котором результат уходит модели и в журнал."""
        return {"ok": self.ok, **({} if self.ok else {"error": self.error}), **self.data}
