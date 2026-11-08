"""Что прогону нужно от внешнего мира."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from jericho.core.evals.entities import EvalCase, PhraseOutcome


class EvalSource(Protocol):
    """Откуда берутся проверочные фразы."""

    def cases(self) -> tuple[EvalCase, ...]: ...


class PhraseRunner(Protocol):
    """Отдаёт фразу Jericho так же, как это делает голос, и возвращает, что произошло."""

    def forget(self) -> None:
        """Начать разговор заново: без недавних реплик и без ожидающего вопроса."""
        ...

    def run(self, phrase: str) -> PhraseOutcome: ...


class RunStore(Protocol):
    """Хранит прогоны, чтобы сравнить новый с предыдущим."""

    def previous(self) -> Mapping[str, Mapping[str, bool]] | None:
        """Оценки прошлого прогона: ключ фразы → критерий → прошла ли. None — прогонов ещё не было."""
        ...

    def save(self, record: Mapping[str, object]) -> str:
        """Сохраняет прогон и возвращает, куда."""
        ...
