"""Общий вид ошибки внешнего мира."""

from __future__ import annotations

from typing import ClassVar


class PortError(Exception):
    """Внешняя система не выполнила просьбу. `code` — как об этом узнаёт модель в ответе инструмента."""

    code: ClassVar[str] = "port_error"
