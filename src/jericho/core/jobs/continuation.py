"""Продолжение фоновой работы (`then`): что сделать, когда работа удастся, и с каким контекстом безопасности."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum

from jericho.core.jobs.entities import JobOutcome


class ContinuationState(StrEnum):
    """Путь записи. Переходы — атомарно, под замком книги (`ContinuationBook`): одно продолжение — один запуск."""

    PENDING = "pending"                      # ждёт свою работу
    CLAIMED = "claimed"                      # работу кончил процесс, который его взял; фраза ещё не начата
    STARTED = "started"                      # фраза продолжения начата: повторять нельзя
    DONE = "done"                            # фраза ответила
    ASKED = "asked"                          # не пошло само (срок, занятость): ждёт решения человека — `job_continue`
    DROPPED = "dropped"                      # не будет выполнено: работа не удалась, присутствие не то
    OUTCOME_UNKNOWN = "outcome_unknown"      # процесс упал после начала фразы: что сделано, неизвестно


@dataclass(frozen=True, slots=True)
class Chain:
    """Цепочка «сделай, потом…»: корень, глубина звена и абсолютный срок автопродолжения (ревью 110, №6).

    Доверенные поля: их пишет код из записи родителя, а не модель. Звено после «да» наследует и срок — он прошёл,
    поэтому следующее звено снова придёт вопросом."""

    root: str
    depth: int
    deadline: datetime


@dataclass(frozen=True, slots=True)
class Carried:
    """Контекст безопасности исходной фразы: что в ней читалось. Продолжение начинает с него, а не с чистого листа —
    иначе вынос наружу после чужого текста или файлов с машины прошёл бы без «да» (ревью 110, №1)."""

    private_read: bool = False
    local_read: bool = False
    foreign: tuple[str, ...] = ()
    chain: Chain | None = None

    def with_foreign(self, source: str) -> Carried:
        return replace(self, foreign=tuple(sorted({*self.foreign, source})))


@dataclass(frozen=True, slots=True)
class Continuation:
    """Запись продолжения. `text` — поручение словами пользователя; в журнал вызова ручки оно не идёт (`private`)."""

    id: str
    job: str                       # работа, после которой выполнять: другая работа это продолжение не возьмёт
    text: str
    user: str                      # чьё поручение (`JERICHO_USER`): чужой процесс его не возьмёт
    attended: bool                 # был ли рядом человек: продолжение идёт так же, как исходная фраза
    carried: Carried
    chain: Chain
    created: datetime
    state: ContinuationState = ContinuationState.PENDING
    reason: str = ""               # почему не пошло само (`asked`, `dropped`)
    result: JobOutcome | None = None    # итог работы — для продолжения после «да»
    title: str = ""                # заголовок работы — для блока результата
    task_id: str = ""              # задача плана асинхронности (АС1); пока пусто
    history: tuple[str, ...] = field(default=())     # пройденные состояния — для разбора, что случилось
