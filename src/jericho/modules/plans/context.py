"""Строка о планах в общем промпте: по ней «продолжай» понятно и после паузы."""

from __future__ import annotations

from jericho.modules.plans.board import PlanBoard
from jericho.modules.plans.entities import Plan, StepState


class PlansLine:
    """Подстановка `{{plans}}`: у каждого плана — сколько сделано и следующий шаг. Весь план — через plan_show."""

    def __init__(self, board: PlanBoard) -> None:
        self._board = board

    def values(self) -> dict[str, str]:
        plans = self._board.all()
        return {"plans": "\n".join(map(self._line, plans)) if plans else "Планов нет."}

    @staticmethod
    def _line(plan: Plan) -> str:
        head = f"- «{plan.title}» (id {plan.id}): сделано {plan.finished} из {len(plan.steps)}"
        if plan.complete:
            return f"{head}; все шаги пройдены"
        if plan.next is None:
            failed = [str(number) for number, step in enumerate(plan.steps, start=1) if step.state is StepState.FAILED]
            return f"{head}; открытых шагов нет, не вышли шаги {', '.join(failed)}"
        step = plan.steps[plan.next - 1]
        if step.state is StepState.AWAITING:
            return f"{head}; шаг {plan.next} ждёт подтверждения пользователя — сверь со страницей: {step.text}"
        return f"{head}; следующий — шаг {plan.next}: {step.text}"
