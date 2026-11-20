"""История фоновых работ по журналу: что идёт, чем кончилось, было ли уже то же дело."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime

import psutil

from jericho.core.jobs.entities import JobOutcome, JobParams, JobRecord, JobStatus, JobTicket
from jericho.core.journal.protocols import JournalReader


def process_alive(pid: int) -> bool:
    """Жив ли процесс — только вопрос системе. Не `os.kill(pid, 0)`: на Windows `0` — это `CTRL_C_EVENT`, и вызов
    послал бы Ctrl+C, а не проверил (ревью 111, №2)."""
    return psutil.pid_exists(pid)


@dataclass(frozen=True, slots=True)
class JobState:
    """Работа, как её видно по журналу: когда начата и итог. Итога нет — `outcome` None (идёт или оборвалась)."""

    ticket: JobTicket
    started: datetime
    outcome: JobOutcome | None
    alive: bool = False        # без итога: процесс работы ещё есть

    @property
    def status(self) -> JobStatus | None:
        """Итог; без итога — None, пока процесс жив, иначе `outcome_unknown`: процесс пропал, не записав итога."""
        if self.outcome is not None:
            return self.outcome.status
        return None if self.alive else JobStatus.OUTCOME_UNKNOWN


class JobHistory:
    """Читает `job_started`/`job_finished` из журнала. Пишет их `JobJournal` в процессе самой работы."""

    SCAN = 5000        # сколько последних записей журнала смотреть: как `read_journal` — несколько недель

    def __init__(self, journal: JournalReader, alive: Callable[[int], bool] = process_alive) -> None:
        self._journal = journal
        self._alive = alive

    def since(self, earliest: datetime) -> list[JobState]:
        """Работы, начатые не раньше `earliest`, от старых к новым."""
        started: dict[str, tuple[datetime, JobRecord]] = {}
        finished: dict[str, JobOutcome] = {}
        for time, record in self._records():
            if record.outcome is not None:
                finished[record.ticket.job] = record.outcome
            elif time >= earliest:
                started[record.ticket.job] = (time, record)
        return [
            JobState(record.ticket, time, finished.get(job), job not in finished and record.pid > 0 and self._alive(record.pid))
            for job, (time, record) in started.items()
        ]

    def succeeded(self, kind: str, params: JobParams) -> JobOutcome | None:
        """Последний успешный итог того же дела — вида и тех же параметров; не было — None."""
        same = JobTicket("", kind, "", params)
        done = [record for _, record in self._records() if record.succeeded and record.ticket.same_deed(same)]
        return done[-1].outcome if done else None

    def _records(self) -> Iterator[tuple[datetime, JobRecord]]:
        for entry in self._journal.tail(self.SCAN):
            if (record := JobRecord.of(entry)) is not None:
                yield entry.time, record
