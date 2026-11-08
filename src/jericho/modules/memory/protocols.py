"""Где лежит память."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from jericho.modules.memory.entities import Memory


class MemoryStore(Protocol):
    def load(self) -> list[Memory]: ...

    def save(self, memories: Sequence[Memory]) -> None: ...
