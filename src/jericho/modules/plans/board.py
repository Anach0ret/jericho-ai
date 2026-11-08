"""Доска планов: создать, найти, отметить шаг, закрыть."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime

from jericho.core.services.ids import short_id
from jericho.core.services.lock import ExclusiveLock, Unlocked
from jericho.core.services.locked_list import LockedList
from jericho.modules.plans.entities import Plan, Step, StepState
from jericho.modules.plans.protocols import PlanStore


class PlanBoard:
    """Свой замок нужен: замок фразы не охватывает окно на панели, прогон плана без человека и другого пользователя.
    Поэтому каждое изменение — под замком списка и над свежими планами по id (`LockedList`)."""

    def __init__(self, store: PlanStore, now: Callable[[], datetime], lock: ExclusiveLock | None = None) -> None:
        self._plans = LockedList(store, lock or Unlocked())
        self._now = now

    def all(self) -> list[Plan]:
        return self._plans.load()

    def find(self, plan_id: str | None = None) -> Plan | None:
        """План по id; без id — тот, что идёт: последний из незаконченных, а нет таких — последний вообще."""
        plans = self.all()
        if plan_id is not None:
            return next((plan for plan in plans if plan.id == plan_id), None)
        going = [plan for plan in plans if plan.next is not None]
        if going:
            return going[-1]
        return plans[-1] if plans else None

    def create(self, title: str, steps: Sequence[str]) -> Plan:
        with self._plans.changing() as plans:
            plan = Plan(short_id({plan.id for plan in plans}), title, tuple(Step(text) for text in steps), self._now())
            plans.append(plan)
        return plan

    def mark(self, plan: Plan, number: int, state: StepState, outcome: str) -> Plan:
        """Отметка — на свежем плане с тем же id: отметки других шагов, сделанные тем временем, остаются.
        Пройденный план убирается сам (журнал 29.10.2026: висел в окне с «Продолжить», и «закрыть?» путало «да»).
        План с невышедшими шагами остаётся: повторить их или бросить, решает человек. План уже закрыли — отметка
        никуда не пишется."""
        with self._plans.changing() as plans:
            fresh = next((other for other in plans if other.id == plan.id), plan)
            changed = fresh.marked(number, state, outcome)
            plans[:] = [changed if other.id == plan.id else other for other in plans if not (other.id == plan.id and changed.complete)]
        return changed

    def close(self, plan_id: str) -> Plan | None:
        with self._plans.changing() as plans:
            closed = next((plan for plan in plans if plan.id == plan_id), None)
            plans[:] = [plan for plan in plans if plan.id != plan_id]
        return closed

