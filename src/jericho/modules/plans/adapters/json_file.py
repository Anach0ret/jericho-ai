"""Планы в файле JSON в папке состояния: переживают паузу в разговоре и перезапуск."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from jericho.core.services.adapters.json_file import JsonStateFile
from jericho.modules.plans.entities import Plan, Step, StepState


class JsonPlanStore:
    def __init__(self, path: Path) -> None:
        self._file = JsonStateFile(path)

    def load(self) -> list[Plan]:
        """Нет файла — планов нет. Испорченный файл откладывается в сторону, а не затирается."""
        return self._file.read(self._parsed, [])

    def save(self, items: Sequence[Plan]) -> None:
        self._file.write([self._record(plan) for plan in items], indent=2)

    @staticmethod
    def _record(plan: Plan) -> dict[str, object]:
        return {
            "id": plan.id,
            "title": plan.title,
            "created": plan.created.isoformat(),
            "steps": [{"text": step.text, "state": step.state.value, "outcome": step.outcome} for step in plan.steps],
        }

    @staticmethod
    def _parsed(records: Any) -> list[Plan]:
        return [
            Plan(
                id=record["id"],
                title=record["title"],
                steps=tuple(Step(step["text"], StepState(step["state"]), step["outcome"]) for step in record["steps"]),
                created=datetime.fromisoformat(record["created"]),
            )
            for record in records
        ]
