"""Книга продолжений в файле JSON в папке состояния: работа идёт в другом процессе и переживает перезапуск."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from jericho.core.jobs.continuation import Carried, Chain, Continuation, ContinuationState
from jericho.core.jobs.entities import JobOutcome, JobStatus
from jericho.core.services.adapters.json_file import JsonStateFile


class JsonContinuationStore:
    def __init__(self, path: Path) -> None:
        self._file = JsonStateFile(path)

    def load(self) -> list[Continuation]:
        """Нет файла — продолжений нет. Испорченный файл откладывается в сторону, а не затирается."""
        return self._file.read(self._parsed, [])

    def save(self, items: Sequence[Continuation]) -> None:
        self._file.write([self._record(item) for item in items], indent=2)

    @staticmethod
    def _record(item: Continuation) -> dict[str, object]:
        carried, result = item.carried, item.result
        return {
            "id": item.id, "job": item.job, "text": item.text, "user": item.user, "attended": item.attended,
            "carried": {"private_read": carried.private_read, "local_read": carried.local_read, "foreign": list(carried.foreign)},
            "chain": _chain(item.chain), "created": item.created.isoformat(), "state": item.state.value, "reason": item.reason,
            "result": None if result is None else {"status": result.status.value, "summary": result.summary, "artifact": result.artifact},
            "title": item.title, "task_id": item.task_id, "history": list(item.history),
        }

    @staticmethod
    def _parsed(records: Any) -> list[Continuation]:
        return [
            Continuation(
                id=record["id"], job=record["job"], text=record["text"], user=record["user"], attended=record["attended"],
                carried=Carried(record["carried"]["private_read"], record["carried"]["local_read"], tuple(record["carried"]["foreign"])),
                chain=Chain(record["chain"]["root"], record["chain"]["depth"], datetime.fromisoformat(record["chain"]["deadline"])),
                created=datetime.fromisoformat(record["created"]), state=ContinuationState(record["state"]), reason=record["reason"],
                result=None if record["result"] is None else JobOutcome(
                    JobStatus(record["result"]["status"]), record["result"]["summary"], record["result"]["artifact"],
                ),
                title=record["title"], task_id=record["task_id"], history=tuple(record["history"]),
            )
            for record in records
        ]


def _chain(chain: Chain) -> dict[str, object]:
    return {"root": chain.root, "depth": chain.depth, "deadline": chain.deadline.isoformat()}
