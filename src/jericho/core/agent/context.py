"""Что каркас сам сообщает модели: который час и вопрос, на который ассистент ждёт «да»."""

from __future__ import annotations

from jericho.core.services.calendar import MONTHS, WEEKDAYS
from jericho.core.services.clock import Clock
from jericho.core.services.confirmation import ConfirmationStore


class PendingQuestion:
    """Подстановка `{{pending_confirmation}}` для раздела о подтверждениях."""

    def __init__(self, confirmations: ConfirmationStore, attended: bool = True) -> None:
        self._confirmations = confirmations
        self._attended = attended

    def values(self) -> dict[str, str]:
        if not self._attended:      # чужой вопрос не показываем: подтвердить его в этом запуске нельзя
            return {"pending_confirmation": "Рядом никого нет: подтвердить ничего нельзя, `confirm()` не вызывай."}
        pending = self._confirmations.pending()
        if pending is None:
            return {"pending_confirmation": "Сейчас подтверждения ничего не ждёт."}
        return {"pending_confirmation": f"**Ждёт подтверждения:** {pending.summary}. Ответ «да» → вызови `confirm()`."}


class Now:
    """Подстановка `{{now}}`: день недели, дата и время. Своих часов у модели нет; время берётся у часов ядра.

    Без неё «сегодня» и «сейчас идёт» модель угадывает по найденным страницам (журнал 13.10.2026: во время
    матча ответила, что сегодня матчей нет). Раздел промпта, которому дата нужна, вставляет подстановку сам.
    """

    def __init__(self, clock: Clock) -> None:
        self._clock = clock

    def values(self) -> dict[str, str]:
        now = self._clock.now()
        date = f"{now.day} {MONTHS[now.month - 1]} {now.year} года"
        # Пояс — числом: модель, которая пишет срок с поясом («завтра в 9» → …T09:00+02:00), иначе его угадывает.
        return {"now": f"{WEEKDAYS[now.weekday()]}, {date}, {now:%H:%M} (UTC{now:%:z})"}
