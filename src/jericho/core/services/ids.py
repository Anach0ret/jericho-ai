"""Короткие id записей: план, памятку, отложенное поручение пользователь может прочитать и назвать голосом."""

from __future__ import annotations

import secrets
from collections.abc import Container

SHORT = 3       # байт — шесть знаков: записей немного, а id должен быть удобен человеку


def short_id(taken: Container[str] = (), size: int = SHORT) -> str:
    """Случайный id, которого ещё нет среди `taken`."""
    candidate = secrets.token_hex(size)
    while candidate in taken:
        candidate = secrets.token_hex(size)
    return candidate
