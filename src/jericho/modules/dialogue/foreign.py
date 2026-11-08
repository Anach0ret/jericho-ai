"""Чей чужой текст был в этой фразе: прочитанный в ней (по журналу — ручки работают и в сервере ручек) и унаследованный."""

from __future__ import annotations

from jericho.core.journal.protocols import JournalReader
from jericho.core.services.foreign import ForeignText


class ForeignReadInRun:
    """Источники, с которыми запоминается ответ фразы: события `foreign` своего запуска (журнал общий у процесса фразы
    и её сервера ручек) и то, что учтено в процессе фразы, — в том числе восстановленное из прошлых ответов.

    Унаследованное тоже едет дальше: продолжение может пересказывать чужой текст, а без этого пометка пропадала, как
    только исходный обмен выходил из памяти разговора (ревью 02.11.2026, П2 №3, П3b №2).
    """

    _TAIL = 500

    def __init__(self, journal: JournalReader, run_id: str, foreign: ForeignText) -> None:
        self._journal = journal
        self._run_id = run_id
        self._foreign = foreign

    def __call__(self) -> tuple[str, ...]:
        found = (
            str(entry.details.get("source", ""))
            for entry in self._journal.tail(self._TAIL)
            if entry.run == self._run_id and entry.event == "foreign"
        )
        return tuple(sorted({source for source in found if source} | self._foreign.sources))
