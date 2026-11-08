"""Модуль ядра «планы»: большая работа из многих шагов — по одному шагу за фразу, с паузами сколько угодно.

План сохраняется после «да» на показанный список (настройка `confirm_create`), шаги отмечает модель, следующий шаг
она видит в общем промпте (`{{plans}}`). Пройти план без вопросов — `plan_run`: отдельный запуск `plans --run`
гонит шаги фразой за фразой. Окно на панели показывает планы из снимка `status`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from jericho.core.management.base import Command
from jericho.core.modules.config import ModuleConfig, ModuleServices
from jericho.core.prompting.protocols import PromptContext
from jericho.core.services.adapters.file_lock import FileLock
from jericho.core.services.adapters.memory_list import MemoryList
from jericho.core.services.lock import Unlocked
from jericho.core.services.output import output_for
from jericho.core.services.paths import Paths
from jericho.core.tools.tool import Tool
from jericho.modules.plans.adapters.json_file import JsonPlanStore
from jericho.modules.plans.board import PlanBoard
from jericho.modules.plans.command import PlansCommand
from jericho.modules.plans.context import PlansLine
from jericho.modules.plans.entities import Plan
from jericho.modules.plans.protocols import PlanStore
from jericho.modules.plans.run import PlanRun
from jericho.modules.plans.settings import PlansSettings
from jericho.modules.plans.tools import ClosePlan, CreatePlan, MarkStep, RunPlan, ShowPlan, described

if TYPE_CHECKING:
    from jericho.core.agent.handle_phrase import HandlePhrase


class PlansModule(ModuleConfig):
    name = "plans"
    FILE = "plans.json"
    LOCK = "plans.lock"              # изменения списка планов — по одному: окно, прогон и фраза
    LOCK_WAIT = 5.0                  # секунд: запись списка — доли секунды
    RUN_LOCK = "plans.run.lock"      # план проходит один запуск за раз

    def ready(self, services: ModuleServices) -> None:
        self._services = services
        self._settings = services.settings.section(self.name, PlansSettings)
        core = services.core
        store: PlanStore = MemoryList[Plan]() if core.dry_run else JsonPlanStore(core.paths.state_dir / self.FILE)
        lock = Unlocked() if core.dry_run else FileLock(core.paths.state_dir / self.LOCK, self.LOCK_WAIT)
        self._board = PlanBoard(store, core.clock.now, lock)

    def tools(self) -> Sequence[Tool[Any]]:
        board, services = self._board, self._services
        return (
            CreatePlan(board, services.core.confirmation, self._settings.confirm_create),
            ShowPlan(board),
            MarkStep(board),
            ClosePlan(board),
            RunPlan(board, services.core.runner, services.program),
        )

    def contexts(self) -> Sequence[PromptContext]:
        return (PlansLine(self._board),)

    def commands(self, handle_phrase: HandlePhrase) -> Sequence[Command]:
        services = self._services
        output = output_for(services.settings.output, services.program.name)
        lock = FileLock(services.core.paths.state_dir / self.RUN_LOCK)
        return (PlansCommand(self._board, PlanRun(self._board, handle_phrase, output, lock), services.relaunch),)

    def status(self) -> Mapping[str, object]:
        """Для окна на панели: планы с шагами — что сделано, что дальше; убрать план — командой `plans --close`."""
        plans = self._board.all()
        return {"plans": [described(plan) for plan in plans]} if plans else {}

    def eval_files(self, paths: Paths) -> Sequence[Path]:
        return (paths.state_dir / self.FILE,)
