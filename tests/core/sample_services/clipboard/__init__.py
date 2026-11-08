"""Пробная служба для тестов каркаса."""

from typing import Protocol


class Clipboard(Protocol):
    def text(self) -> str: ...


__all__ = ["Clipboard"]
