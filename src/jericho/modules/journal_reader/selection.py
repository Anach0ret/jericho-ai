"""Отбор из журнала: условия запроса, общие для отдельных записей и для эпизодов."""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class Selection:
    """Время, ручка и текст. Условие, которое не задано, пропускает всё; заданные складываются."""

    earliest: datetime | None = None
    tool: str | None = None
    contains: str | None = None

    def passes(self, time: datetime, tools: Collection[object], text: str) -> bool:
        return (
            (self.earliest is None or time >= self.earliest)
            and (self.tool is None or self.tool in tools)
            and (self.contains is None or self.contains.casefold() in text.casefold())
        )
