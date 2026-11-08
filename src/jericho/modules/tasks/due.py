"""Команда терминала `due`: исполнить наступившие отложенные поручения. Её раз в минуту зовёт тик."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from jericho.core.agent.entities import AgentReply, ReplyStatus
from jericho.core.services.lock import ExclusiveLock
from jericho.core.services.output import Output
from jericho.core.services.relaunch import Relaunch, relaunched
from jericho.modules.tasks.entities import Deferred, DeferredKind, DeferredState
from jericho.modules.tasks.queue import DeferredQueue
from jericho.modules.tasks.settings import DeferredSettings
from jericho.modules.tasks.when import duration

if TYPE_CHECKING:
    from jericho.core.agent.handle_phrase import HandlePhrase


class DueCommand:
    """Почти каждый тик ничего не находит и выходит сразу — не беря замка и не трогая модель.

    Наступившее исполняется без человека рядом, как задача из настроек: запущенная из терминала, команда
    запускает себя заново с этой отметкой. Правило — «не больше одного раза»: поручение отмечается `running`
    до исполнения, и упавший посредине запуск его не повторит. Лучше пропустить, чем дважды отправить.

    Запуски идут по одному (замок `runs`): долгое поручение может не уложиться в минуту, и следующий тик просто
    выходит. Поэтому `running`, найденное под этим замком, — след упавшего запуска: оно отмечается неудачей.
    """

    name = "due"
    help = "исполнить наступившие отложенные поручения без человека рядом — так их зовёт тик раз в минуту"

    LATE = timedelta(minutes=2)      # раньше этого опоздание не называется: тик и так идёт раз в минуту
    INTERRUPTED = "исполнение прервалось — ассистент упал или был остановлен"

    def __init__(
        self,
        queue: DeferredQueue,
        handle_phrase: HandlePhrase,
        output: Output,
        relaunch: Relaunch,
        runs: ExclusiveLock,
        settings: DeferredSettings,
        now: Callable[[], datetime],
    ) -> None:
        self._queue = queue
        self._handle_phrase = handle_phrase
        self._output = output
        self._relaunch = relaunch
        self._runs = runs
        self._grace = timedelta(minutes=settings.grace_minutes)
        self._keep = timedelta(days=settings.keep_days)
        self._now = now

    def configure(self, parser: argparse.ArgumentParser) -> None:
        pass

    def run(self, args: argparse.Namespace) -> None:
        if not self._queue.has_due() or relaunched(self._relaunch, self.name):
            return
        if not self._runs.acquire():
            return      # предыдущий запуск ещё исполняет — наступившее он и возьмёт
        try:
            states = self._run_due()
        finally:
            self._runs.release()
        if any(state.failed for state in states):
            raise SystemExit(1)

    def _run_due(self) -> list[DeferredState]:
        for item in self._queue.fail_interrupted(self.INTERRUPTED):
            self._output.deliver(item.text, AgentReply(ReplyStatus.FAILED, f"Не выполнил «{item.text}»: {self.INTERRUPTED}"))
        states: list[DeferredState] = []
        while (item := self._queue.take_next()) is not None:
            state = self._execute(item)
            if state is DeferredState.PENDING:
                break      # ассистент занят фразой человека — остальное подождёт следующего тика
            states.append(state)
        self._queue.prune(self._keep)
        return states

    def _execute(self, item: Deferred) -> DeferredState:
        """Исполняет и отмечает в очереди; возвращает, чем кончилось."""
        late = item.late(self._now())
        if item.kind is DeferredKind.REMIND:
            message = f"Напоминание: {item.text}" + (f" (опоздало на {duration(late)})" if late >= self.LATE else "")
            self._output.deliver(item.text, AgentReply(ReplyStatus.DONE, message))
            return self._finish(item, DeferredState.DONE)
        if late > self._grace:
            message = f"Не выполнил «{item.text}»: срок прошёл {duration(late)} назад, пока ассистент был выключен"
            self._output.deliver(item.text, AgentReply(ReplyStatus.REFUSED, message))
            return self._finish(item, DeferredState.MISSED, message)
        reply = self._handle_phrase.execute(item.text)
        if reply == self._handle_phrase.busy:
            self._queue.release(item)
            return DeferredState.PENDING
        self._output.deliver(item.text, reply)
        return self._finish(item, DeferredState.after(reply.status), reply.message)

    def _finish(self, item: Deferred, state: DeferredState, outcome: str = "") -> DeferredState:
        self._queue.finish(item, state, outcome)
        return state
