"""Список записей в памяти процесса — хранилище «вхолостую» и в прогонах проверочных фраз: живёт до конца процесса
и никуда не пишется. Подходит к любому порту вида `load() → list`, `save(items)`: планы, памятки, поручения."""

from __future__ import annotations

from collections.abc import Sequence


class MemoryList[T]:
    def __init__(self, items: Sequence[T] = ()) -> None:
        self._items = list(items)

    def load(self) -> list[T]:
        return list(self._items)

    def save(self, items: Sequence[T]) -> None:
        self._items = list(items)
