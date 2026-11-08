"""План и его шаги."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum


class StepState(StrEnum):
    PENDING = "pending"      # ещё не делали
    AWAITING = "awaiting"    # доведён до конца, последнее подтверждение — за пользователем в другом месте (окно сайта)
    DONE = "done"
    SKIPPED = "skipped"      # пользователь сказал пропустить
    FAILED = "failed"        # не вышло: почему — в итоге шага

    @property
    def open(self) -> bool:
        """Шаг ещё не закрыт: его делают или проверяют следующим."""
        return self in (StepState.PENDING, StepState.AWAITING)


@dataclass(frozen=True, slots=True)
class Step:
    text: str                # что сделать — так, чтобы шаг выполнила модель, которая этого разговора не видела
    state: StepState = StepState.PENDING
    outcome: str = ""        # короткий итог: что вышло или почему нет


@dataclass(frozen=True, slots=True)
class Plan:
    id: str
    title: str
    steps: tuple[Step, ...]
    created: datetime

    @property
    def next(self) -> int | None:
        """Номер (с 1) первого незакрытого шага — его делают или проверяют; None — план пройден."""
        return next((number for number, step in enumerate(self.steps, start=1) if step.state.open), None)

    @property
    def finished(self) -> int:
        return sum(not step.state.open for step in self.steps)

    @property
    def complete(self) -> bool:
        """Все шаги сделаны или пропущены: делать и решать больше нечего."""
        return all(step.state in (StepState.DONE, StepState.SKIPPED) for step in self.steps)

    def marked(self, number: int, state: StepState, outcome: str) -> Plan:
        steps = list(self.steps)
        steps[number - 1] = replace(steps[number - 1], state=state, outcome=outcome)
        return replace(self, steps=tuple(steps))
