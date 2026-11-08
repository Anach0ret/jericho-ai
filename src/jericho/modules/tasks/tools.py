"""Ручки отложенных поручений: поставить, посмотреть, снять.

Поставленное исполнится без человека рядом — поэтому `schedule` всегда ждёт «да», а срок в вопросе называет
код, а не модель: человек на слух проверяет, что именно поставлено, и ловит ошибку перевода «завтра в 9».
Без человека поставить нельзя: `schedule` — EFFECT, и политика риска отказывает запуску по расписанию.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import ClassVar, Literal

from pydantic import AwareDatetime, Field

from jericho.core.services.confirmation import ConfirmationGate
from jericho.core.tools.consent import require_consent
from jericho.core.tools.description import ToolDescription
from jericho.core.tools.request import ToolRequest
from jericho.core.tools.result import ToolRefusal, ToolResult
from jericho.core.tools.risk import Approval, Risk
from jericho.core.tools.tool import Tool
from jericho.modules.tasks.entities import Deferred, DeferredKind, DeferredState
from jericho.modules.tasks.queue import DeferredQueue
from jericho.modules.tasks.settings import DeferredSettings
from jericho.modules.tasks.when import spoken_at


class ScheduleRequest(ToolRequest):
    kind: Literal["remind", "do"] = Field(
        description=(
            "remind — в срок только напомнить (позвонить, выключить, взять с собой: то, что делает сам человек); "
            "do — в срок ассистент сам выполнит поручение своими ручками (собрать сводку, найти, проверить)."
        ),
    )
    text: str = Field(
        min_length=1, max_length=500,
        description=(
            "remind — о чём напомнить, коротко. do — поручение самостоятельной фразой, без «завтра в 9»: "
            "в срок его прочтёт модель, которая этого разговора не видела."
        ),
    )
    at: AwareDatetime = Field(
        description="Когда: дата и время ISO 8601 с поясом, например 2026-10-22T09:00:00+02:00. Считай от текущего времени из промпта.",
    )


class Schedule(Tool[ScheduleRequest]):
    """«Да» спрашивает сама ручка (`Approval.TOOL`): до вопроса она проверяет срок, чтобы не спрашивать о невозможном."""

    name = "schedule"
    risk = Risk.EFFECT
    approval = Approval.TOOL
    request_type = ScheduleRequest
    description = ToolDescription(
        when="просят сделать или напомнить что-то позже: «завтра в 9 …», «через полчаса напомни …», «в пятницу проверь …».",
        does=(
            "ставит отложенное поручение. Первый вызов всегда отвечает needs_confirm: прочитай пользователю summary "
            "дословно — там срок словами — и жди «да». В срок поручение do выполнится без человека: то, что требует "
            "«да» (отправить, закрыть, удалить), тогда сделать нельзя — предупреди об этом сразу."
        ),
        returns='{"ok": true, "id": номер, "when": срок словами}.',
        refusals=(
            "needs_confirm (прочитай summary и дождись «да»), in_past (срок уже прошёл — переспроси), "
            "too_far (дальше horizon_days), too_many (ждут max_pending — предложи снять лишнее), queue_busy (повтори)."
        ),
    )

    IN_PAST = "in_past"
    TOO_FAR = "too_far"
    TOO_MANY = "too_many"
    SLACK = timedelta(minutes=1)      # «сейчас» модели и кода расходятся на секунды

    VERBS: ClassVar[dict[DeferredKind, str]] = {DeferredKind.REMIND: "напомнить", DeferredKind.DO: "выполнить"}

    def __init__(self, queue: DeferredQueue, gate: ConfirmationGate, settings: DeferredSettings, now: Callable[[], datetime]) -> None:
        self._queue = queue
        self._gate = gate
        self._horizon = timedelta(days=settings.horizon_days)
        self._max_pending = settings.max_pending
        self._now = now

    def _run(self, request: ScheduleRequest) -> ToolResult:
        now, kind = self._now(), DeferredKind(request.kind)
        self._check(request.at, now)
        when = spoken_at(request.at, now)
        require_consent(self._gate, self.name, request.model_dump(mode="json"), f"{self.VERBS[kind]} «{request.text}» — {when}")
        item = self._queue.add(kind, request.text, request.at)
        return ToolResult.success(id=item.id, when=when)

    def _check(self, at: datetime, now: datetime) -> None:
        if at < now - self.SLACK:
            raise ToolRefusal(self.IN_PAST, now=now.isoformat(timespec="minutes"))
        if at > now + self._horizon:
            raise ToolRefusal(self.TOO_FAR, horizon_days=self._horizon.days)
        if len(self._queue.pending()) >= self._max_pending:
            raise ToolRefusal(self.TOO_MANY, max_pending=self._max_pending)


class ListScheduledRequest(ToolRequest):
    pass


class ListScheduled(Tool[ListScheduledRequest]):
    name = "list_scheduled"
    risk = Risk.READ
    request_type = ListScheduledRequest
    description = ToolDescription(
        when="спрашивают, что запланировано или что ассистент сделал по расписанию; перед cancel_scheduled.",
        does="показывает ждущие отложенные поручения и исполненные за последние дни.",
        returns=(
            '{"ok": true, "pending": [{"id", "kind", "text", "when"}], "finished": [{"id", "kind", "text", "state", '
            '"outcome"}]}; state: done, failed, missed (опоздало — не выполнено), running.'
        ),
        refusals="нет.",
    )

    def __init__(self, queue: DeferredQueue, now: Callable[[], datetime]) -> None:
        self._queue = queue
        self._now = now

    def _run(self, request: ListScheduledRequest) -> ToolResult:
        now, items = self._now(), self._queue.items()
        waiting = DeferredState.PENDING
        return ToolResult.success(
            pending=[{**self._brief(item), "when": spoken_at(item.at, now)} for item in items if item.state is waiting],
            finished=[{**self._brief(item), "state": item.state.value, "outcome": item.outcome} for item in items if item.state is not waiting],
        )

    @staticmethod
    def _brief(item: Deferred) -> dict[str, object]:
        return {"id": item.id, "kind": item.kind.value, "text": item.text}


class CancelScheduledRequest(ToolRequest):
    ids: list[str] = Field(min_length=1, max_length=50, description="id ждущих поручений — из list_scheduled.")


class CancelScheduled(Tool[CancelScheduledRequest]):
    """Одно поручение снимается сразу; несколько — после «да»: модель могла сопоставить фразу не с теми."""

    name = "cancel_scheduled"
    risk = Risk.CHANGE
    request_type = CancelScheduledRequest
    description = ToolDescription(
        when="просят отменить, снять напоминание или запланированное поручение.",
        does=(
            "снимает ждущие поручения по id: сначала найди их через list_scheduled по тексту. Одно — сразу; "
            "несколько — после «да»."
        ),
        returns='{"ok": true, "cancelled": [тексты]}.',
        refusals="not_found (таких id среди ждущих нет — посмотри list_scheduled), needs_confirm (назови, что снимаешь, и дождись «да»), queue_busy.",
    )

    NOT_FOUND = "not_found"

    def __init__(self, queue: DeferredQueue, gate: ConfirmationGate) -> None:
        self._queue = queue
        self._gate = gate

    def _run(self, request: CancelScheduledRequest) -> ToolResult:
        ids = list(dict.fromkeys(request.ids))
        pending = {item.id: item for item in self._queue.pending()}
        missing = [id_ for id_ in ids if id_ not in pending]
        if missing:
            raise ToolRefusal(self.NOT_FOUND, ids=missing)
        if len(ids) > 1:
            texts = "; ".join(pending[id_].text for id_ in ids)
            require_consent(self._gate, self.name, request.model_dump(mode="json"), f"снять {len(ids)}: {texts}")
        cancelled = self._queue.cancel(ids)
        return ToolResult.success(cancelled=[item.text for item in cancelled])
