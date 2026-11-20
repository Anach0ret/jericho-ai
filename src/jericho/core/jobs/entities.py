"""Фоновая работа: что запущено и чем кончилось. Скачивание, расшифровка, отправка файла, прогон плана."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import ClassVar

from jericho.core.agent.entities import ReplyStatus
from jericho.core.journal.entities import JournalEntry
from jericho.core.services.ids import short_id

JobParams = Mapping[str, str | int | bool]


class JobStatus(StrEnum):
    """Чем кончилась работа — по сути дела, а не по коду выхода (план 110 §2.1).

    «Процесс закончился» — ещё не успех: прогон плана, остановленный на шаге, раньше слал «готово» (ревью 110, №7).
    """

    SUCCEEDED = "succeeded"                  # дело сделано: файл скачан, отправлен, план пройден
    FAILED = "failed"                        # не вышло, и известно почему
    WAITING_USER = "waiting_user"            # остановилась на вопросе к человеку
    STOPPED = "stopped"                      # остановил человек: «стоп», план убран
    OUTCOME_UNKNOWN = "outcome_unknown"      # оборвалась посреди дела: сделано ли что-то наружу, неизвестно

    @property
    def reply(self) -> ReplyStatus:
        """Статус уведомления об итоге."""
        return _REPLIES[self]


_REPLIES = {
    JobStatus.SUCCEEDED: ReplyStatus.DONE, JobStatus.FAILED: ReplyStatus.FAILED, JobStatus.WAITING_USER: ReplyStatus.CLARIFY,
    JobStatus.STOPPED: ReplyStatus.STOPPED, JobStatus.OUTCOME_UNKNOWN: ReplyStatus.FAILED,
}


def new_job_id() -> str:
    """Id работы: 12 знаков — работ в журнале за недели много, а называть его голосом не нужно."""
    return short_id(size=6)


@dataclass(frozen=True, slots=True)
class JobOutcome:
    """Итог работы: статус, итог словами и что получилось — путь к файлу или адрес (`artifact`)."""

    status: JobStatus
    summary: str
    artifact: str = ""

    @classmethod
    def succeeded(cls, summary: str, artifact: str = "") -> JobOutcome:
        return cls(JobStatus.SUCCEEDED, summary, artifact)

    @classmethod
    def failed(cls, summary: str) -> JobOutcome:
        return cls(JobStatus.FAILED, summary)


@dataclass(frozen=True, slots=True)
class JobTicket:
    """Какая работа идёт: id, вид (`videos`, `sendfile`…), заголовок уведомления и параметры запроса.

    Параметры — то, по чему повтор узнаётся тем же делом: у видео адрес, кадр и «только звук». Личного в них нет:
    подпись к файлу, текст переписки сюда не кладутся.
    """

    job: str
    kind: str
    title: str
    params: JobParams = field(default_factory=lambda: MappingProxyType({}))
    continuation: str = ""         # id продолжения (`then`), которое ждёт эту работу; в журнал — только он

    def same_deed(self, other: JobTicket) -> bool:
        """То же дело: вид и параметры совпадают — id и заголовок не в счёт."""
        return (self.kind, dict(self.params)) == (other.kind, dict(other.params))


@dataclass(frozen=True, slots=True)
class JobRecord:
    """Запись о работе в журнале: `job_started` или `job_finished`. Единственное место, где решено, как она лежит.

    У записи об итоге есть и параметры запроса: по ней одной видно, что именно сделано, без поиска запуска.
    """

    STARTED: ClassVar[str] = "job_started"
    FINISHED: ClassVar[str] = "job_finished"

    event: str
    ticket: JobTicket
    pid: int = 0                              # процесс работы — у записи о запуске: жив ли он, если итога нет
    outcome: JobOutcome | None = None         # у записи об итоге

    @property
    def succeeded(self) -> bool:
        return self.outcome is not None and self.outcome.status is JobStatus.SUCCEEDED

    def details(self) -> dict[str, object]:
        ticket = self.ticket
        own: dict[str, object] = {
            "job": ticket.job, "kind": ticket.kind, "title": ticket.title, "params": dict(ticket.params),
            **({"continuation": ticket.continuation} if ticket.continuation else {}),
        }
        if self.outcome is None:
            return {**own, "pid": self.pid}
        outcome = self.outcome
        return {**own, "status": outcome.status.value, "summary": outcome.summary, **({"artifact": outcome.artifact} if outcome.artifact else {})}

    @classmethod
    def of(cls, entry: JournalEntry) -> JobRecord | None:
        """Запись журнала → запись о работе; не о работе или испорчена — None."""
        if entry.event not in (cls.STARTED, cls.FINISHED):
            return None
        details = entry.details
        job, kind, params = details.get("job"), details.get("kind"), details.get("params")
        if not isinstance(job, str) or not isinstance(kind, str) or not isinstance(params, Mapping):
            return None
        ticket = JobTicket(job, kind, _text(details, "title"), MappingProxyType(dict(_params(params))), _text(details, "continuation"))
        if entry.event == cls.STARTED:
            pid = details.get("pid")
            return cls(entry.event, ticket, pid=pid if isinstance(pid, int) else 0)
        try:
            status = JobStatus(_text(details, "status"))
        except ValueError:
            return None
        return cls(entry.event, ticket, outcome=JobOutcome(status, _text(details, "summary"), _text(details, "artifact")))


def _text(details: Mapping[str, object], name: str) -> str:
    value = details.get(name)
    return value if isinstance(value, str) else ""


def _params(raw: Mapping[object, object]) -> dict[str, str | int | bool]:
    return {str(name): value for name, value in raw.items() if isinstance(value, str | int | bool)}
