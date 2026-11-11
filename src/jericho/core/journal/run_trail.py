"""След поручения для уведомления: данные событий, источники чужого текста и личные пометки — по журналу."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from jericho.core.journal.entities import JournalEntry
from jericho.core.journal.private_run import PrivateRun
from jericho.core.journal.protocols import JournalReader

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Trail:
    facts: Mapping[str, Sequence[Any]] = field(default_factory=dict)    # имя события → данные каждого: выборок бывает несколько
    foreign: tuple[str, ...] = ()
    memos: tuple[str, ...] = ()      # были личные ручки: в уведомлении — что сделано, а не пересказ


class RunTrail:
    """Читается при отправке, сразу после поручения. Один процесс (`due`) выполняет несколько поручений с общим номером
    запуска, поэтому каждый вызов берёт записи **после прошлой границы** и ставит свою — событие `notice_trail` в журнале.
    Граница — место в журнале, а не время: у разных записей бывает одна метка до миллисекунды (повтор ревью 11.11.2026);
    следующее уведомление — напоминание без модели или другое поручение — не унаследует факты и пометки прошлого."""

    BOUNDARY = "notice_trail"
    _TAIL = 500

    def __init__(self, journal: JournalReader, run_id: str, mark: Callable[[], None] | None = None) -> None:
        self._journal = journal
        self._run_id = run_id
        self._mark = mark or (lambda: logger.info(self.BOUNDARY))

    def __call__(self) -> Trail:
        entries = self._since_boundary()
        self._mark()
        facts: dict[str, list[Any]] = {}
        for entry in entries:
            if entry.event == "fact" and "fact" in entry.details:
                facts.setdefault(str(entry.details["fact"]), []).append(entry.details.get("value"))
        foreign = sorted({str(entry.details.get("source", "")) for entry in entries if entry.event == "foreign"} - {""})
        return Trail(facts, tuple(foreign), PrivateRun.memos(entries))

    def _since_boundary(self) -> list[JournalEntry]:
        mine = [entry for entry in self._journal.tail(self._TAIL) if entry.run == self._run_id]
        last = max((index for index, entry in enumerate(mine) if entry.event == self.BOUNDARY), default=-1)
        return mine[last + 1 :]


def no_trail() -> Trail:
    return Trail()
