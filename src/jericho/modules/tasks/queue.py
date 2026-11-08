"""Очередь отложенных поручений: одно место, где их ставят, снимают и отдают на исполнение.

Пишут в очередь два процесса — сервер ручек (поставить, снять) и команда `due` (исполнить). Каждое изменение —
«прочитать, поменять, записать» под одним замком: иначе поручение, поставленное в ту же секунду, когда `due`
отмечала исполненное, потерялось бы.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import datetime, timedelta

from jericho.core.errors import PortError
from jericho.core.services.ids import short_id
from jericho.core.services.lock import ExclusiveLock
from jericho.core.services.locked_list import LockedList
from jericho.modules.tasks.entities import Deferred, DeferredKind, DeferredState
from jericho.modules.tasks.protocols import DeferredStore


class QueueBusy(PortError):
    """Замок очереди не освободился вовремя: её держит другой процесс."""

    code = "queue_busy"


class DeferredQueue:

    def __init__(self, store: DeferredStore, lock: ExclusiveLock, now: Callable[[], datetime]) -> None:
        self._list = LockedList(store, lock, QueueBusy)
        self._now = now

    def items(self) -> list[Deferred]:
        return sorted(self._list.load(), key=lambda item: item.at)

    def pending(self) -> list[Deferred]:
        return [item for item in self.items() if item.state is DeferredState.PENDING]

    def has_due(self) -> bool:
        """Есть работа для `due`: наступившее или `running` — его исполняют сейчас или оставил упавший запуск.

        Без замка: так проходит почти каждый тик. То же правило — в `peek.py`.
        """
        now = self._now()
        return any(item.due(now) or item.state is DeferredState.RUNNING for item in self._list.load())

    def add(self, kind: DeferredKind, text: str, at: datetime) -> Deferred:
        with self._list.changing() as items:
            taken = {item.id for item in items}
            item = Deferred(short_id(taken), kind, text, at, self._now())
            items.append(item)
        return item

    def cancel(self, ids: Sequence[str]) -> list[Deferred]:
        """Снимает ждущие поручения с этими id; возвращает снятые. Исполненные остаются в истории."""
        wanted = set(ids)
        with self._list.changing() as items:
            cancelled = [item for item in items if item.id in wanted and item.state is DeferredState.PENDING]
            gone = {item.id for item in cancelled}
            items[:] = [item for item in items if item.id not in gone]
        return cancelled

    def take_next(self) -> Deferred | None:
        """Самое раннее наступившее — уже отмеченное `running` на диске: упавший запуск не исполнит его второй раз.

        По одному, а не все сразу: если исполнение упадёт, застрянет одно поручение, а не все наступившие.
        """
        now = self._now()
        with self._list.changing() as items:
            due = sorted((item for item in items if item.due(now)), key=lambda item: item.at)
            if not due:
                return None
            taken = replace(due[0], state=DeferredState.RUNNING)
            items[:] = [taken if item.id == taken.id else item for item in items]
        return taken

    def finish(self, item: Deferred, state: DeferredState, outcome: str = "") -> None:
        now = self._now()
        self._change(item.id, lambda stored: stored.finish(state, now, outcome))

    def release(self, item: Deferred) -> None:
        """Вернуть взятое поручение в ожидание: исполнить его не дали, а не оно не удалось (ассистент был занят фразой)."""
        self._change(item.id, lambda stored: replace(stored, state=DeferredState.PENDING))

    def fail_interrupted(self, outcome: str) -> list[Deferred]:
        """Поручения, оставшиеся `running` от упавшего запуска, — неудача, а не вечное «исполняется».

        Звать, только держа замок запусков `due`: иначе чужой идущий запуск принят за упавший.
        """
        now = self._now()
        with self._list.changing() as items:
            interrupted = [item for item in items if item.state is DeferredState.RUNNING]
            items[:] = [item.finish(DeferredState.FAILED, now, outcome) if item in interrupted else item for item in items]
        return interrupted

    def prune(self, keep: timedelta) -> None:
        """Убирает завершённые раньше, чем `keep` назад: история нужна, чтобы спросить «что ты сделал утром?»."""
        border = self._now() - keep
        with self._list.changing() as items:
            items[:] = [item for item in items if item.finished is None or item.finished >= border]

    def _change(self, id_: str, change: Callable[[Deferred], Deferred]) -> None:
        with self._list.changing() as items:
            items[:] = [change(item) if item.id == id_ else item for item in items]


