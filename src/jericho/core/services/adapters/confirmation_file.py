"""Ожидающее подтверждение в файле каталога сеанса: живёт свой срок (`confirmation_minutes`) и не переживает выход
из системы. Просроченный вопрос не исчезает молча: его забирают (`take_expired`), чтобы сказать «истёк»."""

from __future__ import annotations

import os
import uuid
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from jericho.core.services.adapters.json_file import JsonStateFile
from jericho.core.services.clock import local_now
from jericho.core.services.confirmation import PendingConfirmation


class JsonFileConfirmationStore:
    """Хранит один вопрос — последний. После срока `ttl` он не ждёт «да», но лежит, пока его не заберут как истёкший."""

    def __init__(self, path: Path, ttl: timedelta = timedelta(minutes=2), clock: Callable[[], datetime] = local_now) -> None:
        self._path = path
        self._file = JsonStateFile(path, clock)
        self._ttl = ttl
        self._clock = clock

    def pending(self) -> PendingConfirmation | None:
        return self._fresh(self._file.read(self._parsed, None))

    def take(self) -> PendingConfirmation | None:
        """Переименование — одно действие: из двух процессов файл достанется одному, второй получит «нет файла»."""
        return self._fresh(self.take_raw())

    def take_expired(self) -> PendingConfirmation | None:
        stale = self._file.read(self._parsed, None)
        if stale is None or self._fresh(stale) is not None:
            return None
        taken = self.take_raw()
        return taken if taken is not None and self._fresh(taken) is None else None

    def take_raw(self) -> PendingConfirmation | None:
        """Забрать как есть, без проверки срока, — одним переименованием (см. `take`)."""
        taken = self._path.with_name(f"{self._path.name}.taken-{uuid.uuid4().hex}")
        try:
            os.replace(self._path, taken)
        except OSError:
            return None
        confirmation = JsonStateFile(taken, self._clock).read(self._parsed, None)
        taken.unlink(missing_ok=True)
        return confirmation

    def mark_reminded(self) -> PendingConfirmation | None:
        pending = self.pending()
        if pending is None:
            return None
        reminded = replace(pending, reminded=True)
        self._file.write(self._record(reminded))
        return reminded

    def _fresh(self, confirmation: PendingConfirmation | None) -> PendingConfirmation | None:
        if confirmation is None:
            return None
        return confirmation if self._clock() - confirmation.asked_at <= self._ttl else None

    @staticmethod
    def _parsed(data: Any) -> PendingConfirmation:
        return PendingConfirmation(
            tool=data["tool"],
            arguments=dict(data["arguments"]),
            summary=data["summary"],
            asked_at=datetime.fromisoformat(data["asked_at"]),
            asked_by=data["asked_by"],
            subject=data.get("subject"),
            approved_by=data.get("approved_by", ""),
            reminded=bool(data.get("reminded", False)),
            id=str(data.get("id", "")),       # вопрос, записанный до 0.62.0, ни одна кнопка не подтвердит — только слово
        )

    def ask(self, tool: str, arguments: Mapping[str, object], summary: str, asked_by: str, subject: object = None) -> None:
        self._file.write(self._record(PendingConfirmation(tool, arguments, summary, self._clock(), asked_by, subject)))

    def approve(self, run_id: str) -> PendingConfirmation | None:
        pending = self.pending()
        if pending is None:
            return None
        approved = replace(pending, approved_by=run_id)
        self._file.write(self._record(approved))
        return approved

    @staticmethod
    def _record(confirmation: PendingConfirmation) -> dict[str, object]:
        return {
            "tool": confirmation.tool,
            "arguments": dict(confirmation.arguments),
            "summary": confirmation.summary,
            "asked_at": confirmation.asked_at.isoformat(),
            "asked_by": confirmation.asked_by,
            "subject": confirmation.subject,
            "approved_by": confirmation.approved_by,
            "reminded": confirmation.reminded,
            "id": confirmation.id,
        }
