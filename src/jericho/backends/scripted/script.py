"""Сценарий: что бэкенд вызовет и ответит на поручение, записанное заранее."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from jericho.core.backends.config import BackendError


@dataclass(frozen=True, slots=True)
class Call:
    tool: str
    arguments: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Step:
    """Одна запись сценария: на какое поручение, какие ручки вызвать и что ответить."""

    when: str                         # слова из поручения; пусто — запись на всё остальное
    calls: tuple[Call, ...]
    reply: Mapping[str, object]       # ответ в выбранной форме: для короткой — status и message

    def fits(self, task: str) -> bool:
        return self.when.casefold() in task.casefold()


def read_script(file: Path) -> tuple[Step, ...]:
    """Файл YAML — список записей `when`, `calls`, `reply`. Запись не того вида — ошибка с её номером."""
    try:
        records: Any = yaml.safe_load(file.read_text(encoding="utf-8")) or []
    except (OSError, yaml.YAMLError) as error:
        raise BackendError(f"{file}: {error}") from error
    if not isinstance(records, list):
        raise BackendError(f"{file}: the script must be a list of records")
    return tuple(_step(record, f"{file}: record {number}") for number, record in enumerate(records, start=1))


def _step(record: Any, where: str) -> Step:
    if not isinstance(record, dict) or not isinstance(record.get("reply"), dict):
        raise BackendError(f"{where}: needs `reply` — the answer in the chosen form, for example status and message")
    calls = record.get("calls") or []
    if not isinstance(calls, list) or not all(isinstance(call, dict) and isinstance(call.get("tool"), str) for call in calls):
        raise BackendError(f"{where}: `calls` must be a list of records with `tool` and optional `arguments`")
    return Step(
        when=str(record.get("when") or ""),
        calls=tuple(Call(call["tool"], dict(call.get("arguments") or {})) for call in calls),
        reply=dict(record["reply"]),
    )
