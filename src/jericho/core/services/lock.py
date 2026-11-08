"""Замок «только один одновременно» между процессами Jericho."""

from __future__ import annotations

from typing import Protocol


class ExclusiveLock(Protocol):
    """Замок между процессами. Сколько ждать занятый замок, решает тот, кто его создал."""

    def acquire(self) -> bool:
        """Взять замок; False — он занят другим процессом и за отведённое время не освободился."""
        ...

    def release(self) -> None: ...


class HeldLock(Protocol):
    """Замок, про который можно узнать, кто его держит."""

    def holder(self) -> int | None:
        """Номер процесса, который держит замок; None — замок свободен."""
        ...


class Unlocked:
    """Замка нет: для сборок, где второй процесс появиться не может (тесты, подставные сценарии)."""

    def acquire(self) -> bool:
        return True

    def release(self) -> None:
        pass
