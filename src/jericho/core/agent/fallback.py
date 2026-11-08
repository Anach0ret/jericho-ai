"""Запасные бэкенды: основная модель упёрлась в лимит — поручение уходит следующей."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from jericho.core.agent.active_backend import ActiveBackend
from jericho.core.agent.entities import BackendAnswer
from jericho.core.agent.protocols import AgentBackend, ModelTimeout, ModelUnavailable
from jericho.core.services.phrase_deadline import PhraseDeadline

logger = logging.getLogger(__name__)


class RunActions(Protocol):
    """Что этот запуск уже сделал — вызовы ручек, которые что-то изменили."""

    def done(self) -> tuple[str, ...]:
        """Имена ручек, успешно вызванных в этом запуске, кроме только читающих. Пусто — повторять безопасно."""
        ...


@dataclass(frozen=True, slots=True)
class NamedBackend:
    name: str                 # как бэкенд назван в журнале: `claude_cli`, `openai_api`
    backend: AgentBackend


class FallbackBackend:
    """Спрашивает бэкенды по очереди: следующий — только если предыдущий ответил `ModelUnavailable`.

    Запасной начинает поручение сначала. Если до сбоя Jericho уже что-то сделал (открыл окно, нажал), запасной
    сделал бы это второй раз — поэтому тогда сбой остаётся сбоем и называет сделанное. Чтение повтором не считается.
    Запасной работает в остатке срока фразы, а не в новом полном сроке; срок вышел — не начинает вовсе (ревью
    02.11.2026, сводка №9).
    """

    def __init__(
        self, backends: Sequence[NamedBackend], actions: RunActions, active: ActiveBackend | None = None,
        deadline: PhraseDeadline | None = None,
    ) -> None:
        self._first, *self._spares = backends
        self._actions = actions
        self._active = active or ActiveBackend()     # кто ведёт фразу — для политики личных данных
        self._deadline = deadline or PhraseDeadline()

    def ask(self, system_prompt: str, phrase: str) -> BackendAnswer:
        failed = self._first
        try:
            return self._answer(self._first, system_prompt, phrase)
        except ModelUnavailable as error:
            failure = error
        for spare in self._spares:
            self._hand_over(failure, failed, spare)
            try:
                return self._answer(spare, system_prompt, phrase)
            except ModelUnavailable as error:
                failure, failed = error, spare
        raise failure

    def _answer(self, named: NamedBackend, system_prompt: str, phrase: str) -> BackendAnswer:
        self._active.name = named.name
        answer = named.backend.ask(system_prompt, phrase)
        return BackendAnswer(answer.structured, {**answer.meta, "backend": named.name})

    def _hand_over(self, failure: ModelUnavailable, failed: NamedBackend, spare: NamedBackend) -> None:
        """Передаёт поручение запасному — или оставляет сбой, если повтор сделал бы что-то второй раз."""
        if self._deadline.passed():
            raise ModelTimeout(f"{failure}; not handed to {spare.name}: the phrase is out of time") from failure
        done = self._actions.done()
        if done:
            raise ModelUnavailable(f"{failure}; not handed to {spare.name}: already done in this phrase — {', '.join(done)}") from failure
        logger.warning("backend_switched", extra={"data": {"backend": failed.name, "next": spare.name, "error": str(failure)[:300]}})
