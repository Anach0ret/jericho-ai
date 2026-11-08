"""Срок на один вызов ручки: не уложилась — вызов обрывается, а не висит дольше самой фразы."""

from __future__ import annotations

import signal
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from types import FrameType


class ToolTimeout(BaseException):
    """Ручка не уложилась в срок. Не `Exception`: широкий `except` внутри ручки не должен его проглотить."""


class Deadline:
    """Обрывает работу, которая идёт дольше заданного, — стандартным таймером процесса (`signal.setitimer`).

    Фраза живёт не дольше срока разговора с моделью. Ручка, которая работает дольше, продолжала бы действовать
    уже после того, как пользователю ответили «не получилось». Поэтому срок ручки меньше срока фразы — это
    проверяют настройки.

    Таймер процесса один и доступен только главному потоку. В другом потоке и во вложенном вызове
    (ручка `confirm` вызывает подтверждённую ручку) срок не ставится: действует срок внешнего вызова.
    """

    def __init__(self, seconds: float | None = None) -> None:
        self.seconds = seconds
        self._armed = False

    @contextmanager
    def limit(self, cap: float | None = None) -> Iterator[None]:
        """`cap` — сколько осталось у всего поручения: ручка не работает дольше него, даже если её срок больше."""
        seconds = self.seconds if cap is None else (cap if self.seconds is None else min(self.seconds, cap))
        if seconds is None or self._armed or threading.current_thread() is not threading.main_thread():
            yield
            return
        previous = signal.signal(signal.SIGALRM, self._expired)
        signal.setitimer(signal.ITIMER_REAL, max(seconds, 0.001))
        self._armed = True
        try:
            yield
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous)
            self._armed = False

    @staticmethod
    def _expired(signum: int, frame: FrameType | None) -> None:
        raise ToolTimeout
