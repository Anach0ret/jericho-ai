"""Порты памяток."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from jericho.modules.playbooks.entities import Playbook


class PlaybookStore(Protocol):
    """Где лежат памятки. Читать и писать целиком: их немного."""

    def load(self) -> list[Playbook]: ...

    def save(self, items: Sequence[Playbook]) -> None: ...
