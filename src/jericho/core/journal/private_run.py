"""Была ли в этой фразе чужая переписка — по журналу: ручки работают и в другом процессе (сервер ручек)."""

from __future__ import annotations

from collections.abc import Iterable

from jericho.core.journal.entities import JournalEntry
from jericho.core.journal.protocols import JournalReader


class PrivateRun:
    """Пометки `memo` вызовов с личными полями (`Tool.private`) своего запуска; пусто — переписки не было.

    Вместо ответа модели их запоминает разговор и пишет журнал фраз: «прочитал чат …», а не пересказ.
    """

    _TAIL = 500
    TOUCHED = "(о переписке — без текста)"      # личная ручка не дала memo: сказано, что было, но не что

    def __init__(self, journal: JournalReader, run_id: str) -> None:
        self._journal = journal
        self._run_id = run_id

    def __call__(self) -> tuple[str, ...]:
        return self.memos(entry for entry in self._journal.tail(self._TAIL) if entry.run == self._run_id)

    @classmethod
    def memos(cls, entries: Iterable[JournalEntry]) -> tuple[str, ...]:
        """Пометки личных вызовов среди этих записей — общий шаг с `RunTrail`."""
        found: list[str] = []
        for entry in entries:
            if entry.event == "tool" and entry.details.get("private"):
                memo = (entry.result or {}).get("memo")
                found.append(memo if isinstance(memo, str) and memo else cls.TOUCHED)
        return tuple(dict.fromkeys(found))
