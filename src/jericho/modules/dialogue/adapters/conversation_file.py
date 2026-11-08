"""Память разговора в небольшом JSON-файле.

Файл лежит в каталоге сеанса ($XDG_RUNTIME_DIR), поэтому после выхода из системы разговор
не сохраняется. Реплики старше срока хранения не возвращаются и при следующей записи стираются.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from jericho.core.agent.entities import AgentReply, ReplyStatus
from jericho.core.services.adapters.json_file import JsonStateFile
from jericho.core.services.clock import local_now
from jericho.modules.dialogue.entities import Exchange


class JsonFileConversationMemory:
    """Хранит несколько последних реплик не дольше заданного срока."""

    def __init__(
        self,
        path: Path,
        ttl: timedelta = timedelta(minutes=2),
        limit: int = 3,
        clock: Callable[[], datetime] = local_now,
    ) -> None:
        self._file = JsonStateFile(path, clock)
        self._ttl = ttl
        self._limit = limit
        self._clock = clock

    def recent(self) -> tuple[Exchange, ...]:
        oldest_allowed = self._clock() - self._ttl
        return tuple(exchange for exchange in self._load() if exchange.time >= oldest_allowed)[-self._limit :]

    def remember(self, phrase: str, reply: AgentReply, foreign: Sequence[str] = ()) -> None:
        exchange = Exchange.of(self._clock(), phrase, reply, tuple(foreign))
        exchanges = [*self.recent(), exchange][-self._limit :]
        self._file.write([
            {
                "time": exchange.time.isoformat(), "phrase": exchange.phrase, "status": exchange.status.value,
                "message": exchange.message, "foreign": list(exchange.foreign), "body": exchange.body,
            }
            for exchange in exchanges
        ])

    def _load(self) -> list[Exchange]:
        """Нет файла — разговора не было; испорченный файл хранилище отложит в сторону и тоже вернёт «пусто»."""
        return self._file.read(self._parsed, [])

    @staticmethod
    def _parsed(records: Any) -> list[Exchange]:
        return [
            Exchange(
                datetime.fromisoformat(record["time"]), record["phrase"], ReplyStatus(record["status"]), record["message"],
                tuple(record.get("foreign", ())), record.get("body", ""),
            )
            for record in records
        ]
