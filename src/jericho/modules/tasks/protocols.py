"""Порты отложенных поручений."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from jericho.modules.tasks.entities import Deferred


class DeferredStore(Protocol):
    """Где лежат отложенные поручения. Читать и писать целиком: их немного, а правду держит один файл."""

    def load(self) -> list[Deferred]: ...

    def save(self, items: Sequence[Deferred]) -> None: ...


class UnitFiles(Protocol):
    """Папка unit-файлов systemd. Все изменения расписания на диске — только через неё: «вхолостую» её подменяют, и
    `timers install` ничего не пишет и не удаляет (ревью 02.11.2026, сводка №6; критика плана 07.11.2026)."""

    def names(self, pattern: str) -> list[str]:
        """Имена файлов по образцу (`home-*.timer`), по алфавиту."""
        ...

    def read(self, name: str) -> str | None:
        """Текст файла; None — файла нет."""
        ...

    def write(self, name: str, text: str) -> None: ...

    def remove(self, name: str) -> None: ...
