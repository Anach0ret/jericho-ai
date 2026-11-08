"""Память в файле JSON рядом с журналом: её можно прочитать и поправить руками."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from jericho.core.services.adapters.json_file import JsonStateFile
from jericho.modules.memory.entities import Memory


class JsonFileMemoryStore:
    """Файл читается при каждом обращении: пишет в него сервер ручек, а читает ещё и процесс, принявший фразу."""

    def __init__(self, path: Path) -> None:
        self._file = JsonStateFile(path)

    def load(self) -> list[Memory]:
        return self._file.read(self._parsed, [])

    def save(self, memories: Sequence[Memory]) -> None:
        self._file.write([
            {"id": m.id, "text": m.text, "tags": list(m.tags), "added": m.added.isoformat(), "used": m.used,
             "last_used": m.last_used.isoformat() if m.last_used else None}
            for m in memories
        ], indent=2)

    @staticmethod
    def _parsed(records: Any) -> list[Memory]:
        return [
            Memory(r["id"], r["text"], tuple(r["tags"]), datetime.fromisoformat(r["added"]), int(r.get("used", 0)),
                   datetime.fromisoformat(r["last_used"]) if r.get("last_used") else None)
            for r in records
        ]
