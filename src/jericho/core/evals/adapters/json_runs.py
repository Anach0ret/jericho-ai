"""Прогоны в файлах JSON: по файлу на прогон, имя — время прогона."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path


class JsonRunStore:
    def __init__(self, directory: Path, clock: Callable[[], datetime] = datetime.now) -> None:
        self._directory = directory
        self._clock = clock

    def previous(self) -> Mapping[str, Mapping[str, bool]] | None:
        files = sorted(self._directory.glob("*.json"))
        if not files:
            return None
        record = json.loads(files[-1].read_text(encoding="utf-8"))
        return {case["key"]: case["marks"] for case in record["cases"]}

    def save(self, record: Mapping[str, object]) -> str:
        self._directory.mkdir(parents=True, exist_ok=True)
        file = self._directory / f"{self._clock():%Y-%m-%d_%H-%M-%S}.json"
        file.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
        return str(file)
