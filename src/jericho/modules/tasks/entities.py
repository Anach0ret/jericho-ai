"""Отложенное поручение: фраза, которую сказали сейчас, а выполнить нужно в названный срок."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum

from jericho.core.agent.entities import ReplyStatus


class DeferredKind(StrEnum):
    REMIND = "remind"    # в срок — только уведомление с текстом; модель не нужна, поэтому доходит всегда
    DO = "do"            # в срок — полный прогон фразы без человека рядом


class DeferredState(StrEnum):
    PENDING = "pending"      # ждёт срока
    RUNNING = "running"      # срок пришёл, исполняется; упавший запуск оставит его здесь, и повтора не будет
    DONE = "done"
    REFUSED = "refused"      # ассистент отказался или спросил, а ответить некому — не выполнено
    FAILED = "failed"
    MISSED = "missed"        # поручение опоздало больше допуска — не выполнено

    @classmethod
    def after(cls, status: ReplyStatus) -> DeferredState:
        """Чем кончилось поручение по ответу ассистента. Выполнено — только `done`: отказ раньше тоже записывался
        выполненным, и планировщик не видел неуспеха (ревью 02.11.2026, П3a №9)."""
        return _AFTER[status]

    @property
    def run_failed(self) -> bool:
        """Не выполнено по вине запуска: планировщик узнаёт это по коду выхода. Опоздавшее (`missed`) — не сбой
        запуска: ассистент был выключен, и пользователь уже получил сообщение."""
        return self in (DeferredState.REFUSED, DeferredState.FAILED)


_AFTER = {
    ReplyStatus.DONE: DeferredState.DONE,
    ReplyStatus.CLARIFY: DeferredState.REFUSED,
    ReplyStatus.REFUSED: DeferredState.REFUSED,
    ReplyStatus.IGNORED: DeferredState.REFUSED,
    ReplyStatus.FAILED: DeferredState.FAILED,
    ReplyStatus.STOPPED: DeferredState.FAILED,
}


@dataclass(frozen=True, slots=True)
class Deferred:
    id: str
    kind: DeferredKind
    text: str                # для DO — самостоятельная фраза: в срок её прочтёт модель без контекста разговора
    at: datetime             # когда выполнить; всегда с поясом
    created: datetime
    state: DeferredState = DeferredState.PENDING
    finished: datetime | None = None
    outcome: str = ""        # короткий итог: что ответил ассистент или почему не выполнено

    def due(self, now: datetime) -> bool:
        return self.state is DeferredState.PENDING and self.at <= now

    def late(self, now: datetime) -> timedelta:
        return max(now - self.at, timedelta(0))

    def finish(self, state: DeferredState, now: datetime, outcome: str = "") -> Deferred:
        return replace(self, state=state, finished=now, outcome=outcome)
