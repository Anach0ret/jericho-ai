"""Двухшаговое подтверждение: действие с последствиями выполняется только после «да» пользователя.

Ручка, которой нужно согласие, спрашивает службу. Служба запоминает **сам вызов** — имя ручки и параметры —
и отвечает «нет, сначала спроси». На «да» в следующей фразе модель вызывает ручку ядра `confirm()`, и ядро
выполняет ровно тот вызов, о котором спрашивало: подтвердить что-то другое нельзя.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PendingConfirmation:
    """Вызов, о котором Jericho спросил и ждёт ответа."""

    tool: str                             # какую ручку выполнить после «да»
    arguments: Mapping[str, object]       # с какими параметрами — как их прислала модель
    summary: str                          # то же человеческими словами — для промпта
    asked_at: datetime
    asked_by: str                         # какой запуск Jericho задал вопрос
    subject: object = None                # на что именно дано согласие: окна по адресам, страница и надпись
    approved_by: str = ""                 # какой запуск услышал «да» пользователя на этот вопрос; пусто — не слышал никто
    reminded: bool = False                # транспорт уже напомнил, что вопрос ждёт ответа
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])   # кнопка «Да» несёт его: подтверждает этот вопрос, не сменивший его

    def same_call(self, tool: str, arguments: Mapping[str, object]) -> bool:
        """Та же ручка с теми же параметрами — объект согласия может и не совпасть."""
        return (self.tool, dict(self.arguments)) == (tool, dict(arguments))

    def about(self, tool: str, arguments: Mapping[str, object], subject: object) -> bool:
        """Тот ли это вызов: та же ручка, те же параметры и тот же объект согласия."""
        return self.same_call(tool, arguments) and self.subject == subject


@dataclass(frozen=True, slots=True)
class Consent:
    """Ответ службы ручке: можно ли выполнять. Если нельзя — вопрос уже записан, осталось спросить пользователя."""

    granted: bool
    changed: bool = False     # «да» было, но на другое: с тех пор окна или страница изменились
    replaced: str = ""        # прежний вопрос, который снят ради нового
    nobody: bool = False      # рядом никого нет: вопрос не записан, ответить на него некому

    def notes(self) -> dict[str, str]:
        """Что добавить в отказ `needs_confirm`, чтобы модель сказала об этом пользователю."""
        notes: dict[str, str] = {}
        if self.nobody:
            notes["nobody"] = "рядом никого нет, спросить некого — действие не выполнено; скажи об этом в ответе"
        if self.changed:
            notes["changed"] = "с прошлого вопроса всё изменилось — прежнее «да» не годится, спроси заново"
        if self.replaced:
            notes["replaced"] = f"прежний вопрос снят: {self.replaced}"
        return notes


class ConfirmationStore(Protocol):
    """Где лежит вопрос, на который Jericho ждёт «да»."""

    def pending(self) -> PendingConfirmation | None:
        """Текущий вопрос; None — вопроса нет или он устарел."""
        ...

    def ask(self, tool: str, arguments: Mapping[str, object], summary: str, asked_by: str, subject: object = None) -> None: ...

    def take(self) -> PendingConfirmation | None:
        """Забрать вопрос одним действием: из двух процессов его получит один. None — вопроса нет или он устарел."""
        ...

    def approve(self, run_id: str) -> PendingConfirmation | None:
        """Отметить, что этот запуск услышал «да» пользователя. None — вопроса нет или он устарел."""
        ...

    def take_expired(self) -> PendingConfirmation | None:
        """Забрать вопрос, если его срок вышел, — чтобы сказать «истёк, ничего не сделано», а не промолчать. None — нет."""
        ...

    def mark_reminded(self) -> PendingConfirmation | None:
        """Отметить, что о ждущем вопросе напомнили. None — вопроса нет или он устарел."""
        ...


class ConfirmationGate:
    """Пропускает действие, только если его подтвердили **следующей** фразой.

    Каждая фраза обрабатывается отдельным запуском Jericho со своим идентификатором. Согласие принимается
    лишь от другого запуска, чем тот, что задал вопрос: модель не может сама спросить и сама же себе
    ответить «да» в пределах одной фразы — между вопросом и действием обязана прозвучать фраза пользователя.

    Согласие даётся на названное, а не на параметры вызова: ручка передаёт `subject` — что именно она
    собирается тронуть. После «да» она выбирает окна или читает страницу заново; если получилось другое,
    согласие не действует, и вопрос задаётся снова.

    «Да» распознаёт не модель, а код, по самой фразе пользователя (`core/agent/consent.py`): однозначное «да»
    на ждущий вопрос отмечает его одобренным этим запуском, «нет» снимает. `grant()` отдаёт вопрос, только если
    его одобрил этот самый запуск: модель, вызвавшая `confirm()` на «нет» или на посторонний вопрос, получит отказ.

    Запуск без человека рядом (`attended=False`) не спрашивает и не подтверждает: его вопрос не ложится
    в хранилище, иначе на него ответило бы чужое «да», и чужой вопрос он не забирает.
    """

    def __init__(self, store: ConfirmationStore, run_id: str, attended: bool = True) -> None:
        self._store = store
        self._run_id = run_id
        self._attended = attended
        self._granted: PendingConfirmation | None = None

    @property
    def attended(self) -> bool:
        return self._attended

    def consent(self, tool: str, arguments: Mapping[str, object], summary: str, subject: object = None) -> Consent:
        """Вопрос ручки: можно ли выполнять? Не `granted` — вызов записан, нужно спросить пользователя."""
        if not self._attended:
            logger.warning("confirmation_unattended", extra={"data": {"tool": tool, "asked": summary}})
            return Consent(granted=False, nobody=True)
        subject = self._plain(subject)
        granted = self._granted
        if granted is not None and granted.same_call(tool, arguments):
            self._granted = None      # согласие действует на один вызов
            if granted.subject == subject:
                return Consent(granted=True)
            logger.warning("confirmation_changed", extra={"data": {"tool": tool, "agreed": granted.subject, "now": subject}})
            self._store.ask(tool, arguments, summary, self._run_id, subject)
            return Consent(granted=False, changed=True)
        return Consent(granted=False, replaced=self._ask(tool, arguments, summary, subject))

    def has_consent(self, tool: str, arguments: Mapping[str, object], subject: object = None) -> bool:
        """Этот ли вызов только что подтвердили? В отличие от `consent`, вопроса не записывает.

        Для ручки, которой согласие нужно не всегда: она должна узнать подтверждённый вызов и пропустить проверки,
        которые в новой фразе уже не имеют смысла.
        """
        granted = self._granted
        if granted is None or not granted.about(tool, arguments, self._plain(subject)):
            return False
        self._granted = None
        return True

    def grant(self) -> PendingConfirmation | None:
        """«Да» пользователя: отдаёт вызов, о котором спрашивали, и разрешает выполнить его один раз.

        None — подтверждать нечего: вопроса не было, он устарел, задан в этой же фразе или его уже забрали.
        """
        if not self._attended:
            return None
        pending = self._store.pending()
        if pending is None or pending.asked_by == self._run_id or pending.approved_by != self._run_id:
            return None
        taken = self._store.take()
        if taken is None or taken.asked_by == self._run_id or taken.approved_by != self._run_id:
            return None
        self._granted = taken
        return taken

    def waiting(self) -> PendingConfirmation | None:
        """Вопрос, который ждёт ответа пользователя (ещё не одобрен), — с его id для кнопок. None — такого нет."""
        pending = self._store.pending() if self._attended else None
        return pending if pending is not None and not pending.approved_by else None

    def question(self) -> str | None:
        """Вопрос, который сейчас ждёт «да» этого пользователя, — для транспорта с кнопками «Да» и «Нет». None — нет."""
        waiting = self.waiting()
        return waiting.summary if waiting is not None else None

    def asked_now(self) -> bool:
        """Вопрос задан в этой фразе и ждёт ответа — тогда вход с кнопками показывает «Да» и «Нет»."""
        waiting = self.waiting()
        return waiting is not None and waiting.asked_by == self._run_id

    def withdraw(self) -> PendingConfirmation | None:
        """Снимает ждущий вопрос: последним пользователь увидел не его, и «да» на другой вопрос его не выполнит."""
        return self._store.take() if self.waiting() is not None else None

    def waiting_for_yes(self) -> bool:
        """Есть вопрос из прошлой фразы, а «да» на него в этой фразе не прозвучало."""
        pending = self._store.pending() if self._attended else None
        return pending is not None and pending.asked_by != self._run_id and pending.approved_by != self._run_id

    def user_said_yes(self) -> PendingConfirmation | None:
        """Вход поручения услышал «да» пользователя. Зовёт только он (`PhraseConsent`), не ручки и не модель."""
        if not self._attended:
            return None
        pending = self._store.pending()
        if pending is None or pending.asked_by == self._run_id:
            return None
        return self._store.approve(self._run_id)

    def take_expired(self) -> PendingConfirmation | None:
        """Ответ пришёл после срока: вопрос забирается, чтобы сказать об этом, а не ответить «подтверждать нечего»."""
        return self._store.take_expired() if self._attended else None

    def user_said_no(self) -> PendingConfirmation | None:
        """Вход поручения услышал «нет»: вопрос снимается, выполнить его уже нельзя. Истёкший не трогается: на него
        ответ — «истёк» (`take_expired`)."""
        if not self._attended or self._store.pending() is None:
            return None
        return self._store.take()

    def _ask(self, tool: str, arguments: Mapping[str, object], summary: str, subject: object) -> str:
        """Записывает вопрос. Возвращает прежний, если он был о другом: его приходится снять, и не молча."""
        previous = self._store.pending()
        self._store.ask(tool, arguments, summary, self._run_id, subject)
        if previous is None or previous.about(tool, arguments, subject):
            return ""
        logger.warning("confirmation_replaced", extra={"data": {"dropped": previous.summary, "tool": previous.tool, "asked": summary}})
        return previous.summary

    @staticmethod
    def _plain(subject: object) -> object:
        """Как после записи в файл и чтения из него: кортеж становится списком — иначе сверка не сойдётся."""
        return json.loads(json.dumps(subject, ensure_ascii=False, sort_keys=True))
