"""Продолжение ставит ручка фоновой работы: «скачай и пришли другу» — `then` у `video_download`."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta

from jericho.core.jobs.book import ContinuationBook
from jericho.core.jobs.carried import CarriedContext
from jericho.core.jobs.continuation import Carried, Chain, Continuation
from jericho.core.services.confirmation import ConfirmationGate
from jericho.core.services.foreign import ForeignText
from jericho.core.services.ids import short_id
from jericho.core.tools.result import ToolRefusal
from jericho.core.tools.session import CallSession


class ContinuationDesk:
    """Записывает продолжение с контекстом этой фразы и цепочкой и отдаёт его id — работе передаётся только он.

    Цепочку (корень, глубину, срок) берёт из перенесённого контекста (`CarriedContext.chain`), а не от модели:
    продолжение, поставленное продолжением, — следующее звено той же цепочки, и пределы держит код.
    После личной переписки или файлов с машины в этой фразе продолжение не ставится: фраза продолжения пошла бы любому
    бэкенду запасной цепочки, а выбрать допущенный для одной фразы работа не может (толкование Claude к ревью 110, №4;
    файлы — ревью 111, №1), — пусть второй шаг будет отдельной просьбой.
    """

    AFTER_PRIVATE = "then_after_private"
    AFTER_LOCAL = "then_after_local"
    TOO_DEEP = "chain_too_deep"
    TOO_LONG = "chain_too_long"

    def __init__(
        self, book: ContinuationBook, carried: CarriedContext, session: CallSession, foreign: ForeignText, gate: ConfirmationGate,
        user: str, now: Callable[[], datetime], auto: timedelta, depth: int, links: int,
    ) -> None:
        self._book = book
        self._carried = carried
        self._session = session
        self._foreign = foreign
        self._gate = gate
        self._user = user
        self._now = now
        self._auto = auto
        self._depth = depth
        self._links = links

    def register(self, text: str, job: str) -> str:
        """Записать продолжение работы `job`; id — работе. Нельзя — отказ с кодом и подсказкой."""
        if self._session.private_read:
            raise ToolRefusal(self.AFTER_PRIVATE, detail="после личной переписки продолжение не ставлю: запусти работу без then, второй шаг — отдельной просьбой")
        if self._session.local_read:
            raise ToolRefusal(self.AFTER_LOCAL, detail="после чтения файлов с машины продолжение не ставлю: запусти работу без then, второй шаг — отдельной просьбой")
        continuation = short_id(size=6)
        self._book.put(Continuation(continuation, job, text, self._user, self._gate.attended, self._context(), self._chain(continuation), self._now()))
        return continuation

    def link(self, job: str) -> str:
        """Фраза-продолжение запускает работу без `then`: звено цепочки без текста; id — работе, пусто — не продолжение.

        Постоянный шаг работы (`analyze`) встанет в это звено и пойдёт в той же цепочке: иначе работа, запущенная
        продолжением, начинала бы свою и обходила глубину, предел звеньев и срок (ревью 111, этап 3, №1). Пределы
        проверяет шаг (`ContinuationBook.lead`), а не запуск: работа без второго шага им не подлежит.
        """
        parent = self._carried.chain
        if parent is None:
            return ""
        continuation = short_id(size=6)
        chain = Chain(parent.root, parent.depth + 1, parent.deadline)
        self._book.put(Continuation(continuation, job, "", self._user, self._gate.attended, self._context(), chain, self._now()))
        return continuation

    def _context(self) -> Carried:
        return Carried(self._session.private_read, self._session.local_read, tuple(sorted(self._foreign.sources)))

    def _chain(self, continuation: str) -> Chain:
        parent = self._carried.chain
        if parent is None:
            return Chain(continuation, 1, self._now() + self._auto)
        if parent.depth + 1 > self._depth:
            raise ToolRefusal(self.TOO_DEEP, limit=self._depth, detail="цепочка продолжений слишком длинная — скажи, что дальше сделаешь по просьбе")
        if self._book.links(parent.root) + 1 > self._links:
            raise ToolRefusal(self.TOO_LONG, limit=self._links, detail="у этой просьбы уже слишком много продолжений — скажи об этом")
        return Chain(parent.root, parent.depth + 1, parent.deadline)
