"""Что запуск уже сделал — по журналу."""

from __future__ import annotations

from collections.abc import Mapping

from jericho.core.journal.entities import JournalEntry
from jericho.core.journal.protocols import JournalReader
from jericho.core.tools.risk import Risk


class JournalRunActions:
    """Успешные вызовы ручек этого запуска, кроме только читающих.

    По журналу, а не счётчиком в памяти: у бэкенда `claude_cli` ручки выполняет отдельный процесс — сервер ручек;
    общий у них только журнал и идентификатор запуска. Ручка, которой нет в списке, считается меняющей.
    """

    _SCAN = 500          # последние записи журнала: запуск — это одна фраза, десятки записей

    def __init__(self, journal: JournalReader, run_id: str, risks: Mapping[str, Risk]) -> None:
        self._journal = journal
        self._run_id = run_id
        self._risks = risks

    def done(self) -> tuple[str, ...]:
        calls = (entry for entry in self._journal.tail(self._SCAN) if entry.run == self._run_id and entry.call_succeeded)
        return tuple(dict.fromkeys(tool for tool in map(self._tool, calls) if self._changes(tool)))

    @staticmethod
    def _tool(entry: JournalEntry) -> str:
        return str(entry.details.get("tool", ""))

    def _changes(self, tool: str) -> bool:
        return self._risks.get(tool, Risk.EFFECT) is not Risk.READ
