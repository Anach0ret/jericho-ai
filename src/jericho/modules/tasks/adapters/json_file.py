"""Отложенные поручения в файле JSON в папке состояния: его удобно прочитать и поправить руками."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from jericho.core.services.adapters.json_file import JsonStateFile
from jericho.modules.tasks.entities import Deferred, DeferredKind, DeferredState


class JsonDeferredStore:
    """Файл читается при каждом обращении: пишет в него сервер ручек, а исполняет поручения команда `due`."""

    def __init__(self, path: Path) -> None:
        self._file = JsonStateFile(path)

    def load(self) -> list[Deferred]:
        """Нет файла — поручений нет. Испорченный файл откладывается в сторону, а не затирается."""
        return self._file.read(self._parsed, [])

    def save(self, items: Sequence[Deferred]) -> None:
        self._file.write([self._record(item) for item in items], indent=2)

    @staticmethod
    def _record(item: Deferred) -> dict[str, object]:
        return {
            "id": item.id,
            "kind": item.kind.value,
            "text": item.text,
            "at": item.at.isoformat(),
            "created": item.created.isoformat(),
            "state": item.state.value,
            "finished": item.finished.isoformat() if item.finished else None,
            "outcome": item.outcome,
        }

    @staticmethod
    def _parsed(records: Any) -> list[Deferred]:
        return [
            Deferred(
                id=record["id"],
                kind=DeferredKind(record["kind"]),
                text=record["text"],
                at=datetime.fromisoformat(record["at"]),
                created=datetime.fromisoformat(record["created"]),
                state=DeferredState(record["state"]),
                finished=datetime.fromisoformat(record["finished"]) if record["finished"] else None,
                outcome=record["outcome"],
            )
            for record in records
        ]
