"""Часы ассистента: который сейчас час — в том поясе, в котором живёт его пользователь."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from zoneinfo import ZoneInfo


def local_now() -> datetime:
    """«Сейчас» с поясом машины — для файлов состояния и журнала, где пояс пользователя не нужен."""
    return datetime.now().astimezone()


class Clock:
    """Служба ядра: одно место, откуда берётся «сейчас».

    Пояс задаёт настройка `timezone`; пусто — пояс машины. Ассистенту на сервере пояс нужен явно: там
    часто стоит UTC, и «сегодня» сменилось бы не тогда, когда у пользователя.
    """

    def __init__(self, timezone: str = "", system: Callable[[], datetime] = datetime.now) -> None:
        self._zone = ZoneInfo(timezone) if timezone else None
        self._system = system

    def now(self) -> datetime:
        """Текущее время с поясом: названным в настройках либо поясом машины."""
        return self._system().astimezone(self._zone)
