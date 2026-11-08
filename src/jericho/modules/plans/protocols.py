"""Порты планов."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from jericho.modules.plans.entities import Plan


class PlanStore(Protocol):
    """Где лежат планы. Читать и писать целиком: их немного."""

    def load(self) -> list[Plan]: ...

    def save(self, items: Sequence[Plan]) -> None: ...
