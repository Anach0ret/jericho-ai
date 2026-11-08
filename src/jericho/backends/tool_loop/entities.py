"""Что ходит между общим циклом и моделью: описание ручки, вызов, ход модели, ответ ручки."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from jericho.core.tools.result import ToolImage


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """Ручка в том виде, в каком её получает модель."""

    name: str
    description: str
    schema: Mapping[str, object]      # схема параметров (JSON Schema)


@dataclass(frozen=True, slots=True)
class ToolCall:
    """Вызов, который модель сделала в своём ходе."""

    id: str                           # по нему модель сопоставит ответ с вызовом
    name: str
    arguments: Mapping[str, object]
    problem: str = ""                 # параметры пришли не JSON-объектом: вызов не выполняется вовсе


@dataclass(frozen=True, slots=True)
class Usage:
    """Сколько токенов ушло на ход: для журнала и подсчёта стоимости."""

    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0            # прочитано из кеша промпта: стоит дешевле

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
            self.cached_tokens + other.cached_tokens,
        )


@dataclass(frozen=True, slots=True)
class ModelTurn:
    """Один ход модели: вызовы ручек и, может быть, текст мимо них."""

    calls: tuple[ToolCall, ...] = ()
    text: str = ""
    usage: Usage = field(default_factory=Usage)


@dataclass(frozen=True, slots=True)
class CallAnswer:
    """Ответ на один вызов — уходит модели в следующем сообщении."""

    call_id: str
    content: Mapping[str, object]
    is_error: bool
    images: tuple[ToolImage, ...] = ()     # кадры, фото: модель с картинками их видит, остальным — пометка
