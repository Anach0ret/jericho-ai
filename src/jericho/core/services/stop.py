"""Остановка поручения, которое выполняется прямо сейчас."""

from __future__ import annotations

import logging
import os
import signal
from collections.abc import Callable

import psutil

from jericho.core.services.lock import HeldLock
from jericho.core.services.process_tree import ProcessTree

logger = logging.getLogger(__name__)


def interrupt(pid: int) -> None:
    """POSIX: SIGINT — прерывание; держатель жив и сам останавливает свои программы (`runner` → `ProcessTree`)."""
    os.kill(pid, signal.SIGINT)


def stop_tree(pid: int) -> None:
    """Windows: прерывания другому процессу там нет — `os.kill` завершает его сразу, и убрать за собой он не успевает.
    Поэтому останавливается всё его дерево: CLI модели, сервер ручек, программа ручки (ревью Codex 08.11.2026, №8)."""
    if not psutil.pid_exists(pid):
        raise ProcessLookupError(pid)
    ProcessTree.stop_pid(pid)


def system_stop() -> Callable[[int], None]:
    return interrupt if hasattr(os, "getsid") else stop_tree


class PhraseStopper:
    """Прерывает процесс, который держит замок поручения.

    Сигнал — обычное прерывание (как Ctrl+C в терминале): сценарий поручения ловит его и отвечает «остановлено»,
    дочерние программы (`claude -p`) закрываются вместе с ним. Ручка, которая в этот момент действует,
    обрывается на полпути: что успело произойти, видно в журнале. На Windows — остановка всего дерева держателя
    сразу (`stop_tree`): «остановлено» он ответить не успеет, но и его программы не продолжат работу.
    """

    def __init__(self, lock: HeldLock, halt: Callable[[int], None] | None = None, own: int | None = None) -> None:
        self._lock = lock
        self._halt = halt or system_stop()
        self._own = own if own is not None else os.getpid()

    def stop(self) -> int | None:
        """Номер остановленного процесса; None — останавливать нечего."""
        holder = self._lock.holder()
        if holder is None or holder == self._own:
            return None
        try:
            self._halt(holder)
        except ProcessLookupError:
            return None      # успел закончить сам
        logger.warning("stop", extra={"data": {"pid": holder}})
        return holder
