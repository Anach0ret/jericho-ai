"""Заметки в файле JSON рядом с журналом: их удобно прочитать и поправить руками."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from jericho.core.services.adapters.json_file import JsonStateFile
from jericho.modules.notes.entities import Note


class JsonFileNoteStore:
    """Файл читается при каждом обращении: пишет в него сервер ручек, а читает ещё и процесс, принявший фразу."""

    def __init__(self, path: Path) -> None:
        self._file = JsonStateFile(path)

    def load(self) -> list[Note]:
        """Нет файла — заметок нет. Испорченный файл хранилище откладывает в сторону: новая заметка его не затрёт."""
        return self._file.read(self._parsed, [])

    def save(self, notes: Sequence[Note]) -> None:
        records = [
            {"skill": note.skill, "kind": note.kind, "name": note.name, "value": note.value, "added": note.added.isoformat()}
            for note in notes
        ]
        self._file.write(records, indent=2)

    @staticmethod
    def _parsed(records: Any) -> list[Note]:
        return [
            Note(record["skill"], record["kind"], record["name"], record["value"], datetime.fromisoformat(record["added"]))
            for record in records
        ]
