"""Журнал фоновой работы: запуск и итог — записями в журнал, итог — ещё и уведомлением."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable

from jericho.core.agent.entities import AgentReply
from jericho.core.jobs.entities import JobOutcome, JobRecord, JobStatus, JobTicket
from jericho.core.jobs.run import ContinuationRun
from jericho.core.services.output import Output

logger = logging.getLogger(__name__)


class JobJournal:
    """Обёртка любой фоновой работы. Работа отдаёт итог (`JobOutcome`), журнал пишет его и сообщает человеку.

    Раньше итог приходил только уведомлением: на «готово?» Jericho не знал, что скачивание кончилось, и качал ролик
    второй раз (журнал home 11.11.2026, план 110). Теперь в журнале — `job_started` и `job_finished` с одним id.
    Исключение посреди работы — итог `outcome_unknown`: что успело уйти наружу, неизвестно, повторять нельзя.
    """

    UNKNOWN = "Работа оборвалась ошибкой: что успело сделаться, неизвестно — проверь, прежде чем повторять"
    QUIET = (JobStatus.SUCCEEDED, JobStatus.WAITING_USER, JobStatus.STOPPED)    # итог по делу, не сбой: уровень INFO

    def __init__(self, output: Output, continuations: ContinuationRun | None = None, pid: Callable[[], int] = os.getpid) -> None:
        self._output = output
        self._continuations = continuations     # нет — продолжений у этих работ не бывает
        self._pid = pid

    def run(self, ticket: JobTicket, work: Callable[[], JobOutcome], lead: str = "") -> JobOutcome:
        """Записать запуск, сделать работу, записать и сообщить итог; удалась — продолжение.

        `lead` — постоянный шаг после удачной работы (разбор расшифровки из настроек): идёт тем же продолжением,
        первым. Записывается после работы: неудача не должна слать второе уведомление «разбор не выполнен».
        """
        self._write(JobRecord(JobRecord.STARTED, ticket, pid=self._pid()), logging.INFO)
        try:
            outcome = work()
        except Exception:
            self.finish(ticket, JobOutcome(JobStatus.OUTCOME_UNKNOWN, self.UNKNOWN))
            raise
        self.finish(ticket, outcome)
        if lead and outcome.status is JobStatus.SUCCEEDED and self._continuations is not None:
            ticket = self._continuations.lead(ticket, lead)
        if ticket.continuation:
            self._continue(ticket, outcome)
        return outcome

    def finish(self, ticket: JobTicket, outcome: JobOutcome) -> JobOutcome:
        """Итог — в журнал и уведомлением; путь или адрес результата — подробностями уведомления."""
        level = logging.INFO if outcome.status in self.QUIET else logging.WARNING
        self._write(JobRecord(JobRecord.FINISHED, ticket, outcome=outcome), level)
        self._output.deliver(ticket.title, AgentReply(outcome.status.reply, outcome.summary, outcome.artifact))
        return outcome

    def _continue(self, ticket: JobTicket, outcome: JobOutcome) -> None:
        if self._continuations is None:
            logger.warning(ContinuationRun.DROPPED, extra={"data": {"continuation": ticket.continuation, "job": ticket.job, "reason": "no_runner"}})
            return
        self._continuations.after(ticket, outcome)

    @staticmethod
    def _write(record: JobRecord, level: int) -> None:
        logger.log(level, record.event, extra={"data": record.details()})
