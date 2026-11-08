"""Команда терминала «планы» — для человека и для окна на панели."""

from __future__ import annotations

import argparse
import logging
from typing import ClassVar

from jericho.core.services.relaunch import Relaunch, relaunched
from jericho.modules.plans.board import PlanBoard
from jericho.modules.plans.run import PlanRun

logger = logging.getLogger(__name__)


class PlansCommand:
    name = "plans"
    help = "планы: без аргументов — список с шагами; --close ID — убрать план (без «да»); --run ID — пройти до конца без вопросов"

    MARKS: ClassVar[dict[str, str]] = {"pending": " ", "awaiting": "?", "done": "x", "skipped": "-", "failed": "!"}

    def __init__(self, board: PlanBoard, runner: PlanRun | None = None, relaunch: Relaunch | None = None) -> None:
        self._board = board
        self._runner = runner       # нет — прохождение без вопросов этому запуску недоступно
        self._relaunch = relaunch   # прохождение — только без человека: запуск заново с отметкой, до сборки

    def configure(self, parser: argparse.ArgumentParser) -> None:
        actions = parser.add_mutually_exclusive_group()
        actions.add_argument("--close", metavar="ID", help="id плана — из списка")
        actions.add_argument("--run", metavar="ID", help="id плана — пройти оставшиеся шаги без вопросов")

    def run(self, args: argparse.Namespace) -> None:
        if args.run:
            if self._runner is None or self._relaunch is None:
                raise SystemExit("прохождение плана здесь недоступно")
            if relaunched(self._relaunch, self.name, "--run", args.run):     # сводка ревью 02.11.2026, №8
                return
            print(self._runner.run(args.run))
            return
        if args.close:
            closed = self._board.close(args.close)
            if closed is None:
                raise SystemExit(f"плана {args.close} нет")
            logger.info("plan_closed", extra={"data": {"id": closed.id, "title": closed.title, "by": "command"}})
            print(f"Убран план: {closed.title}")
            return
        for plan in self._board.all():
            print(f"{plan.id}  {plan.title} — {plan.finished}/{len(plan.steps)}")
            for number, step in enumerate(plan.steps, start=1):
                outcome = f" — {step.outcome}" if step.outcome else ""
                print(f"  [{self.MARKS[step.state.value]}] {number}. {step.text}{outcome}")
