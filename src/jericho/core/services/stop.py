"""Остановка поручения, которое выполняется прямо сейчас."""

from __future__ import annotations

import logging
import os
import signal
from collections.abc import Callable

from jericho.core.services.lock import HeldLock

logger = logging.getLogger(__name__)


class PhraseStopper:
    """Прерывает процесс, который держит замок поручения.

    Сигнал — обычное прерывание (как Ctrl+C в терминале): сценарий поручения ловит его и отвечает «остановлено»,
    дочерние программы (`claude -p`) закрываются вместе с ним. Ручка, которая в этот момент действует,
    обрывается на полпути: что успело произойти, видно в журнале.
    """

    def __init__(self, lock: HeldLock, kill: Callable[[int, int], None] = os.kill, own: int | None = None) -> None:
        self._lock = lock
        self._kill = kill
        self._own = own if own is not None else os.getpid()

    def stop(self) -> int | None:
        """Номер остановленного процесса; None — останавливать нечего."""
        holder = self._lock.holder()
        if holder is None or holder == self._own:
            return None
        try:
            self._kill(holder, signal.SIGINT)
        except ProcessLookupError:
            return None      # успел закончить сам
        logger.warning("stop", extra={"data": {"pid": holder}})
        return holder
