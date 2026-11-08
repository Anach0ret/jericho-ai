"""Памятки в файле JSON в папке состояния."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from jericho.core.services.adapters.json_file import JsonStateFile
from jericho.modules.playbooks.entities import Playbook, Suggestion


class JsonPlaybookStore:
    def __init__(self, path: Path) -> None:
        self._file = JsonStateFile(path)

    def load(self) -> list[Playbook]:
        """Нет файла — памяток нет. Испорченный файл откладывается в сторону, а не затирается."""
        return self._file.read(self._parsed, [])

    def save(self, items: Sequence[Playbook]) -> None:
        self._file.write([self._record(playbook) for playbook in items], indent=2)

    @staticmethod
    def _record(playbook: Playbook) -> dict[str, object]:
        return {
            "id": playbook.id,
            "title": playbook.title,
            "site": playbook.site,
            "text": playbook.text,
            "created": playbook.created.isoformat(),
            "used": playbook.used.isoformat() if playbook.used else None,
            "suggestions": [
                {"id": item.id, "text": item.text, "reason": item.reason, "created": item.created.isoformat()}
                for item in playbook.suggestions
            ],
        }

    @staticmethod
    def _parsed(records: Any) -> list[Playbook]:
        return [
            Playbook(
                id=record["id"],
                title=record["title"],
                site=record["site"],
                text=record["text"],
                created=datetime.fromisoformat(record["created"]),
                used=datetime.fromisoformat(record["used"]) if record["used"] else None,
                suggestions=tuple(
                    Suggestion(item["id"], item["text"], item["reason"], datetime.fromisoformat(item["created"]))
                    for item in record["suggestions"]
                ),
            )
            for record in records
        ]
