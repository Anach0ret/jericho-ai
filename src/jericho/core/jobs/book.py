"""Книга продолжений: записи в файле состояния, переходы — под одним замком для всех процессов."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta

from jericho.core.jobs.continuation import Carried, Chain, Continuation, ContinuationState
from jericho.core.services.ids import short_id
from jericho.core.services.locked_list import LockedList

State = ContinuationState


class ContinuationBook:
    """Взять продолжение может только тот, кто вправе: процесс своей работы (`claim`) или ручка `job_continue` после
    «да» (`take_asked`) — переход проверяет состояние, работу и пользователя под замком, поэтому одно продолжение не
    выполнится дважды, а чужое или подменённое не выполнится вовсе (ревью 110, №5). Записи старше `keep` уходят сами.
    """

    FINAL = frozenset({State.DONE, State.DROPPED, State.OUTCOME_UNKNOWN})
    LEAD = "{lead}\n\nПосле этого: {then}"

    def __init__(self, items: LockedList[Continuation], now: Callable[[], datetime], keep: timedelta) -> None:
        self._items = items
        self._now = now
        self._keep = keep

    def put(self, item: Continuation) -> None:
        with self._items.changing() as items:
            self._purge(items)
            items.append(item)

    def lead(self, job: str, continuation: str, user: str, attended: bool, text: str, depth: int, links: int) -> Continuation | None:
        """Постоянный шаг работы (разбор после расшифровки) — первым в её продолжении. None — шага не будет.

        Нет id — новая запись этого процесса, корень цепочки; её срок — срок хранения, а не окно автопродолжения: шаг
        задан настройкой, а не старой просьбой. Контекст безопасности у неё чистый: в процессе работы до шага ничего не
        читалось. Есть id — только ждущая запись этой работы и пользователя: `then` ручки или звено цепочки без текста
        (работу запустило продолжение); шаг встаёт перед `then` — второму шагу нужен ответ первого. Взятая, выполненная
        или пропавшая запись не заменяется новой (повторный запуск с теми же id, ревью 111, этап 3, №3) — None.
        Звено глубже `depth` или сверх `links` звеньев цепочки — запись бросается (`dropped`) с причиной.
        """
        with self._items.changing() as items:
            self._purge(items)
            if not continuation:
                own, now = short_id(size=6), self._now()
                items.append(Continuation(own, job, text, user, attended, Carried(), Chain(own, 1, now + self._keep), now))
                return items[-1]
            for index, item in enumerate(items):
                if item.id == continuation and item.state is State.PENDING and item.job == job and item.user == user:
                    items[index] = self._led(item, text, self._beyond(items, item, depth, links))
                    return items[index]
        return None

    def _led(self, item: Continuation, text: str, beyond: str) -> Continuation:
        led = replace(item, text=self.LEAD.format(lead=text, then=item.text) if item.text else text)
        return replace(led, state=State.DROPPED, reason=beyond, history=(*led.history, State.DROPPED.value)) if beyond else led

    @staticmethod
    def _beyond(items: list[Continuation], item: Continuation, depth: int, links: int) -> str:
        if item.chain.depth > depth:
            return f"цепочка продолжений глубже {depth}"
        others = sum(other.chain.root == item.chain.root and bool(other.text) and other.id != item.id for other in items)
        return f"у просьбы уже {links} продолжений" if others + 1 > links else ""

    def links(self, root: str) -> int:
        """Сколько звеньев уже у цепочки с этим корнем. Запись без текста — ещё не звено: шага в ней пока нет."""
        return sum(item.chain.root == root and bool(item.text) for item in self._items.load())

    def asked(self, user: str) -> list[Continuation]:
        """Продолжения этого пользователя, которые ждут его решения."""
        return [item for item in self._items.load() if item.state is State.ASKED and item.user == user and self._fresh(item)]

    def claim(self, continuation: str, job: str, user: str) -> Continuation | None:
        """Работа кончилась: взять её продолжение. Нет, не её, не этого пользователя или уже взято — None."""
        return self._move(continuation, State.CLAIMED, lambda item: item.state is State.PENDING and item.job == job and item.user == user)

    def take_asked(self, continuation: str, user: str) -> Continuation | None:
        """«Да» на отложенное продолжение: взять его, если оно правда ждёт решения этого пользователя."""
        return self._move(continuation, State.CLAIMED, lambda item: item.state is State.ASKED and item.user == user)

    def mark(self, item: Continuation, state: State, reason: str = "") -> Continuation:
        """Следующее состояние взятого продолжения; итог и заголовок работы берутся из `item`. Конечное не меняется."""
        moved = self._move(item.id, state, lambda found: found.state not in self.FINAL, reason, item)
        if moved is None:
            raise LookupError(f"продолжение {item.id} уже закончено или убрано из книги")
        return moved

    def _move(
        self, continuation: str, state: State, allowed: Callable[[Continuation], bool], reason: str = "", source: Continuation | None = None,
    ) -> Continuation | None:
        with self._items.changing() as items:
            self._purge(items)
            for index, item in enumerate(items):
                if item.id == continuation and allowed(item):
                    known = source or item
                    items[index] = replace(
                        item, state=state, reason=reason or item.reason, result=known.result or item.result, title=known.title or item.title,
                        history=(*item.history, state.value),
                    )
                    return items[index]
        return None

    def _fresh(self, item: Continuation) -> bool:
        return self._now() - item.created <= self._keep

    def _purge(self, items: list[Continuation]) -> None:
        items[:] = [item for item in items if self._fresh(item)]
