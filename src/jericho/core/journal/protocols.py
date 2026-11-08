"""Журнал: чтение записей для разбора."""

from __future__ import annotations

from typing import Protocol

from jericho.core.journal.entities import JournalEntry


class JournalReader(Protocol):
    """Чтение журнала для разбора: последние записи, от старых к новым."""

    def tail(self, limit: int) -> list[JournalEntry]: ...
