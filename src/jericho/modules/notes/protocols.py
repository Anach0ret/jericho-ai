"""Что заметкам нужно от внешнего мира: место, где они переживают фразу."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from jericho.modules.notes.entities import Note


class NoteStore(Protocol):
    def load(self) -> list[Note]: ...

    def save(self, notes: Sequence[Note]) -> None: ...
