"""Вопросы «да?», которые ждут ответа пользователей бота: напомнить, если затянулось, и сказать, что истёк, — не молчать.

В чате человек отвечает не сразу: через полчаса, через час. Сам вопрос живёт свой срок (`confirmation_minutes`), но
без этого наблюдателя его конец немой — «да» после срока уходит в пустоту. Наблюдатель — часть постоянного приёма
(`inbox`): раз в `EVERY` секунд смотрит вопрос каждого пользователя из `inbox.users` и кладёт в ящик транспорта
напоминание (с кнопками «Да/Нет») или «истёк, ничего не сделано». Сообщение адресовано чату пользователя: в личной
переписке с ботом номер чата — его номер.

Истёкший вопрос забирается одним переименованием (`take_expired`): если пользователь как раз ответил «да», вопрос
достанется кому-то одному — его поручению (оно скажет «истёк») или наблюдателю, — и «истёк» придёт один раз.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from datetime import datetime, timedelta

from jericho.core.agent.wording import RUSSIAN, Wording
from jericho.core.services.adapters.confirmation_file import JsonFileConfirmationStore
from jericho.core.services.clock import local_now
from jericho.core.services.confirmation import PendingConfirmation
from jericho.core.services.mailbox import Mailbox
from jericho.core.services.paths import Paths

logger = logging.getLogger(__name__)


class QuestionWatch:
    EVERY = 15.0       # секунд между обходами: напоминание и «истёк» не обязаны приходить в ту же секунду

    def __init__(
        self, users: Iterable[str], paths: Paths, ttl: timedelta, remind: timedelta | None, outbox: Mailbox,
        clock: Callable[[], datetime] = local_now, wording: Wording = RUSSIAN,
    ) -> None:
        self._users = tuple(users)
        self._paths = paths
        self._ttl = ttl
        self._remind = remind          # None — не напоминать
        self._outbox = outbox
        self._clock = clock
        self._wording = wording

    def tick(self) -> None:
        for user in self._users:
            store = JsonFileConfirmationStore(self._paths.for_user(user).confirmation, self._ttl, self._clock)
            if (expired := store.take_expired()) is not None:
                logger.warning("confirmation_expired", extra={"data": {"user": user, "asked": expired.summary, "asked_at": expired.asked_at.isoformat()}})
                self._outbox.post(self._expired(user, expired))
            elif (pending := store.pending()) is not None and self._due(pending) and store.mark_reminded() is not None:
                logger.info("confirmation_reminded", extra={"data": {"user": user, "asked": pending.summary}})
                self._outbox.post(self._reminder(user, pending))

    def _due(self, pending: PendingConfirmation) -> bool:
        """Напомнить один раз, если вопрос ждёт дольше `remind` и «да» на него ещё не слышали."""
        waited = self._clock() - pending.asked_at
        return self._remind is not None and not pending.reminded and not pending.approved_by and waited >= self._remind

    def _reminder(self, user: str, pending: PendingConfirmation) -> dict[str, object]:
        until = pending.asked_at + self._ttl
        return {
            "chat": user, "user": user, "task": "confirmation", "status": "clarify",
            "title": self._wording.reminder_title.format(question=pending.summary),
            "text": self._wording.reminder_text.format(until=f"{until:%H:%M}"),
            "confirm": pending.summary, "confirm_id": pending.id,
        }

    def _expired(self, user: str, expired: PendingConfirmation) -> dict[str, object]:
        return {
            "chat": user, "user": user, "task": "confirmation", "status": "stopped",
            "title": self._wording.expired_title.format(question=expired.summary), "text": self._wording.expired_text,
        }
