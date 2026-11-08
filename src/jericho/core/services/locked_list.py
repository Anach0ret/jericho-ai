"""Список в файле состояния, который меняют несколько процессов: изменение — под одним замком."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from typing import Protocol

from jericho.core.errors import PortError
from jericho.core.services.lock import ExclusiveLock


class ListStore[T](Protocol):
    """Где лежит список: читать и писать целиком."""

    def load(self) -> list[T]: ...

    def save(self, items: Sequence[T]) -> None: ...


class StateBusy(PortError):
    """Замок не освободился вовремя: список меняет другой процесс."""

    code = "state_busy"


class LockedList[T]:
    """Каждое изменение — «прочитать свежее, поменять, записать» под одним замком.

    Атомарная подмена файла защищает от оборванной записи, но не от потерянной: два процесса прочли одно и то же, и
    запись второго стирала изменение первого — отметку шага плана, принятое дополнение памятки (ревью 02.11.2026,
    П3a №8). Так уже работала очередь отложенных поручений; теперь это общее для всех таких списков.
    """

    def __init__(self, store: ListStore[T], lock: ExclusiveLock, busy: Callable[[], PortError] = StateBusy) -> None:
        self._store = store
        self._lock = lock
        self._busy = busy

    def load(self) -> list[T]:
        """Без замка: файл подменяется целиком, читатель видит старое или новое, но не половину."""
        return self._store.load()

    @contextmanager
    def changing(self) -> Iterator[list[T]]:
        """Список под замком; изменённый на месте — записывается. Не изменился — файл не трогается."""
        if not self._lock.acquire():
            raise self._busy()
        try:
            items = self._store.load()
            before = list(items)
            yield items
            if items != before:
                self._store.save(items)
        finally:
            self._lock.release()
