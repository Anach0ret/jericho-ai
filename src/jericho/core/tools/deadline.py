"""Срок на один вызов ручки: не уложилась — вызов обрывается, а не висит дольше самой фразы.

Как обрывать — дело ОС: на Linux и macOS — таймер процесса и сигнал (`AlarmTimer`), на Windows таймера процесса нет —
поток-таймер просит интерпретатор прервать главный поток (`InterruptTimer`). Что каждый из них обещает — в
`docs/security.md`, «Чего каркас не обещает».
"""

from __future__ import annotations

import _thread
import signal
import threading
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from types import FrameType
from typing import Any, Protocol


class ToolTimeout(BaseException):
    """Ручка не уложилась в срок. Не `Exception`: широкий `except` внутри ручки не должен его проглотить."""


class Timer(Protocol):
    """Обрывает тело `running` исключением `ToolTimeout`, если оно идёт дольше `seconds`. Только главный поток."""

    def running(self, seconds: float) -> AbstractContextManager[None]: ...


Handler = Callable[[int, FrameType | None], Any] | int | signal.Handlers | None   # что вернул `signal.signal`


def _expired(signum: int, frame: FrameType | None) -> None:
    raise ToolTimeout


class AlarmTimer:
    """Linux, macOS: таймер процесса (`signal.setitimer`) и `SIGALRM`. Прерывает и ожидание, которое ОС прерывает
    сигналом (`time.sleep`, чтение сокета); посреди операции в C — нет."""

    @contextmanager
    def running(self, seconds: float) -> Iterator[None]:
        previous = signal.signal(signal.SIGALRM, _expired)
        signal.setitimer(signal.ITIMER_REAL, max(seconds, 0.001))
        try:
            yield
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous)


class InterruptTimer:
    """Без таймера процесса (Windows): по сроку поток-таймер зовёт `_thread.interrupt_main` со своим сигналом.

    Прерывается исполняющийся Python-код — когда интерпретатор обработает прерывание. Блокирующая операция
    (ожидание сети, файла, `time.sleep`) задерживает его до своего конца: автор ручки задаёт ей конечный таймаут.
    Сигнал — не `SIGINT`: Ctrl+C пользователя остаётся остановкой фразы, а не сроком ручки. На Windows — `SIGBREAK`.
    """

    def __init__(self, signum: signal.Signals | None = None) -> None:
        self._signum = signum if signum is not None else signal.SIGBREAK

    @contextmanager
    def running(self, seconds: float) -> Iterator[None]:
        armed = threading.Event()
        lock = threading.Lock()

        def fire() -> None:
            with lock:
                if armed.is_set():
                    _thread.interrupt_main(self._signum)

        previous = signal.signal(self._signum, _expired)
        timer = threading.Timer(max(seconds, 0.001), fire)
        timer.daemon = True
        armed.set()
        timer.start()
        try:
            yield
        finally:
            with lock:
                armed.clear()      # после этого таймер прерывания уже не попросит
            timer.cancel()
            self._restore(previous)

    def _restore(self, previous: Handler) -> None:
        """Прерывание, о котором таймер успел попросить, интерпретатор обработает до смены обработчика — нашим, и
        оно станет `ToolTimeout`. Обработчик возвращается в любом случае: иначе следующий сигнал ушёл бы в наш."""
        expired = False
        while True:
            try:
                signal.signal(self._signum, signal.SIG_DFL if previous is None else previous)   # None — ставили не из Python
                break
            except ToolTimeout:
                expired = True
        if expired:
            raise ToolTimeout


def system_timer() -> Timer:
    """Таймер этой ОС: таймер процесса, где он есть, иначе — прерывание главного потока."""
    return AlarmTimer() if hasattr(signal, "setitimer") else InterruptTimer()


class Deadline:
    """Обрывает работу, которая идёт дольше заданного.

    Фраза живёт не дольше срока разговора с моделью. Ручка, которая работает дольше, продолжала бы действовать
    уже после того, как пользователю ответили «не получилось». Поэтому срок ручки меньше срока фразы — это
    проверяют настройки.

    Таймер обрывает только главный поток. В другом потоке и во вложенном вызове (ручка `confirm` вызывает
    подтверждённую ручку) срок не ставится: действует срок внешнего вызова.
    """

    def __init__(self, seconds: float | None = None, timer: Timer | None = None) -> None:
        self.seconds = seconds
        self._timer = timer or system_timer()
        self._armed = False

    @contextmanager
    def limit(self, cap: float | None = None) -> Iterator[None]:
        """`cap` — сколько осталось у всего поручения: ручка не работает дольше него, даже если её срок больше."""
        seconds = self.seconds if cap is None else (cap if self.seconds is None else min(self.seconds, cap))
        if seconds is None or self._armed or threading.current_thread() is not threading.main_thread():
            yield
            return
        self._armed = True
        try:
            with self._timer.running(seconds):
                yield
        finally:
            self._armed = False
