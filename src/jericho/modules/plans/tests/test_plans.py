import argparse
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from jericho.core.agent.entities import AgentReply, ReplyStatus
from jericho.core.modules.config import ModuleServices
from jericho.core.services.adapters.file_lock import FileLock
from jericho.core.services.adapters.memory_list import MemoryList
from jericho.core.services.confirmation import ConfirmationGate
from jericho.core.services.lock import Unlocked
from jericho.core.services.locked_list import StateBusy
from jericho.core.services.program import Program
from jericho.core.testing import Confirmations, execute, say_yes
from jericho.core.testing.fakes import fake_core
from jericho.modules.plans.adapters.json_file import JsonPlanStore
from jericho.modules.plans.board import PlanBoard
from jericho.modules.plans.command import PlansCommand
from jericho.modules.plans.context import PlansLine
from jericho.modules.plans.entities import Plan, StepState
from jericho.modules.plans.module import PlansModule
from jericho.modules.plans.run import PlanRun
from jericho.modules.plans.settings import PlansSettings
from jericho.modules.plans.tools import ClosePlan, CreatePlan, MarkStep, RunPlan, ShowPlan

NOON = datetime(2026, 10, 29, 12, 0)
TESTS = {"title": "Тесты модуля 1", "steps": ["Пройти тест к уроку 5", "Пройти тест к уроку 9", "Пройти тест к уроку 10"]}


def board(store: MemoryList[Plan] | JsonPlanStore | None = None) -> PlanBoard:
    return PlanBoard(store or MemoryList[Plan](), lambda: NOON)


def saved(steps: list[str] | None = None) -> PlanBoard:
    plans = board()
    plans.create(TESTS["title"], steps or TESTS["steps"])
    return plans


class TestCreatePlan:
    def test_plan_is_saved_only_after_yes_to_the_list_shown(self) -> None:
        """Шаги часто собраны со страницы, а план живёт дольше фразы: что в него войдёт, решает человек."""
        plans, store = board(), Confirmations()

        asked = execute(CreatePlan(plans, ConfirmationGate(store, "run-1")), TESTS)
        nothing_yet = plans.all()
        gate = ConfirmationGate(store, "run-2")
        created = say_yes(gate, CreatePlan(plans, gate))

        assert asked.error == "needs_confirm" and nothing_yet == []
        assert asked.data["summary"] == "сохранить план «Тесты модуля 1»: 1) Пройти тест к уроку 5; 2) Пройти тест к уроку 9; 3) Пройти тест к уроку 10"
        assert created.ok and created.data["plan"]["next"] == 1  # pyright: ignore[reportIndexIssue]
        assert [plan.title for plan in plans.all()] == ["Тесты модуля 1"]

    def test_owner_may_save_plans_without_asking(self) -> None:
        plans, store = board(), Confirmations()

        result = execute(CreatePlan(plans, ConfirmationGate(store, "run-1"), confirm=False), TESTS)

        assert (result.ok, store.pending(), len(plans.all())) == (True, None, 1)

    def test_too_many_plans_are_refused_before_asking(self) -> None:
        plans, store = board(), Confirmations()
        for number in range(2):
            plans.create(f"План {number}", ["раз", "два"])

        result = execute(CreatePlan(plans, ConfirmationGate(store, "run-1"), limit=2), TESTS)

        assert (result.error, len(result.data["plans"]), store.pending()) == ("too_many_plans", 2, None)  # pyright: ignore[reportArgumentType]

    @pytest.mark.parametrize("steps", [["один шаг"], ["", "второй"], ["x" * 401, "второй"]])
    def test_bad_steps_are_refused(self, steps: list[str]) -> None:
        assert execute(CreatePlan(board(), ConfirmationGate(Confirmations(), "run-1")), {**TESTS, "steps": steps}).error == "invalid_parameters"


class TestSteps:
    def test_marked_step_moves_the_plan_to_the_next(self) -> None:
        plans = saved()

        result = execute(MarkStep(plans), {"step": 1, "state": "done", "outcome": "5 из 5"})

        plan = plans.find()
        assert result.ok and plan is not None
        assert (plan.next, plan.finished, plan.steps[0].outcome) == (2, 1, "5 из 5")

    def test_skipped_and_failed_count_as_finished_and_pending_returns_the_step(self) -> None:
        plans = saved()
        execute(MarkStep(plans), {"step": 1, "state": "skipped"})
        execute(MarkStep(plans), {"step": 2, "state": "failed", "outcome": "тест закрыт"})
        execute(MarkStep(plans), {"step": 1, "state": "pending"})

        plan = plans.find()
        assert plan is not None and (plan.next, plan.finished) == (1, 1)
        assert [step.state for step in plan.steps] == [StepState.PENDING, StepState.FAILED, StepState.PENDING]

    def test_awaiting_step_stays_next_until_checked(self) -> None:
        """Отправлено, а подтверждает пользователь в окне сайта: шаг не теряется и не считается сделанным раньше времени."""
        plans = saved()

        execute(MarkStep(plans), {"step": 1, "state": "awaiting", "outcome": "отправлено, подтверждает пользователь"})

        plan = plans.find()
        assert plan is not None and (plan.next, plan.finished) == (1, 0)
        assert PlansLine(plans).values()["plans"].endswith("шаг 1 ждёт подтверждения пользователя — сверь со страницей: Пройти тест к уроку 5")

    def test_plan_with_every_step_done_closes_itself(self) -> None:
        """Журнал 29.10.2026: пройденный план висел в окне с «Продолжить», а вопрос «закрыть?» путал следующие «да»."""
        plans = saved(["раз", "два"])
        execute(MarkStep(plans), {"step": 1, "state": "skipped"})

        result = execute(MarkStep(plans), {"step": 2, "state": "done"})

        assert (result.ok, result.data["closed"], plans.all()) == (True, True, [])

    def test_plan_with_a_failed_step_stays_for_the_person_to_decide(self) -> None:
        plans = saved(["раз", "два"])
        execute(MarkStep(plans), {"step": 1, "state": "done"})

        result = execute(MarkStep(plans), {"step": 2, "state": "failed", "outcome": "кнопки нет"})

        plan = plans.find()
        assert "closed" not in result.data and plan is not None and plan.next is None
        assert PlansLine(plans).values()["plans"].endswith("сделано 2 из 2; открытых шагов нет, не вышли шаги 2")

    def test_step_beyond_the_plan_is_refused(self) -> None:
        result = execute(MarkStep(saved()), {"step": 4, "state": "done"})

        assert (result.error, result.data["steps"]) == ("no_such_step", 3)

    def test_without_plans_the_model_is_told_so(self) -> None:
        assert execute(ShowPlan(board()), {}).error == "plan_not_found"


class TestFind:
    def test_going_plan_wins_over_a_finished_newer_one(self) -> None:
        plans = board()
        going = plans.create("идёт", ["раз", "два"])
        done = plans.create("без открытых шагов", ["раз", "два"])
        done = plans.mark(done, 1, StepState.DONE, "")
        plans.mark(done, 2, StepState.FAILED, "")

        assert plans.find() == going

    def test_closed_plan_is_gone(self) -> None:
        plans = saved()

        result = execute(ClosePlan(plans), {})

        assert (result.ok, result.data["closed"], plans.all()) == (True, "Тесты модуля 1", [])


class TestPromptLine:
    def test_line_names_progress_and_the_next_step(self) -> None:
        plans = saved()
        plan = plans.find()
        assert plan is not None
        plans.mark(plan, 1, StepState.DONE, "")

        line = PlansLine(plans).values()["plans"]

        assert line == f"- «Тесты модуля 1» (id {plan.id}): сделано 1 из 3; следующий — шаг 2: Пройти тест к уроку 9"

    def test_without_plans_the_line_says_so(self) -> None:
        assert PlansLine(board()).values() == {"plans": "Планов нет."}


class TestStorage:
    def test_plans_survive_between_processes(self, tmp_path: Path) -> None:
        file = tmp_path / "plans.json"
        first = board(JsonPlanStore(file))
        plan = first.create(TESTS["title"], TESTS["steps"])
        first.mark(plan, 2, StepState.FAILED, "закрыт")

        again = board(JsonPlanStore(file)).find(plan.id)

        assert again is not None and again.steps[1].state is StepState.FAILED and again.steps[1].outcome == "закрыт"


class TestCommand:
    def test_person_closes_a_plan_from_the_window(self, capsys: pytest.CaptureFixture[str]) -> None:
        plans = saved()
        plan = plans.find()
        assert plan is not None

        PlansCommand(plans).run(argparse.Namespace(close=plan.id, run=None))

        assert plans.all() == [] and "Убран план: Тесты модуля 1" in capsys.readouterr().out

    def test_unknown_plan_is_an_error(self) -> None:
        with pytest.raises(SystemExit, match="нет"):
            PlansCommand(board()).run(argparse.Namespace(close="nope", run=None))


class Phrases:
    """Ассистент для прогона: на каждую фразу отмечает следующий шаг тем, что вернёт `answer`."""

    busy = AgentReply(ReplyStatus.FAILED, "занят")

    def __init__(self, plans: PlanBoard, answer: StepState | AgentReply = StepState.DONE) -> None:
        self.phrases: list[str] = []
        self._plans = plans
        self._answer = answer

    def execute(self, phrase: str) -> AgentReply:
        self.phrases.append(phrase)
        if isinstance(self._answer, AgentReply):
            return self._answer
        plan = self._plans.find()
        if plan is not None and plan.next is not None:
            self._plans.mark(plan, plan.next, self._answer, "")
        return AgentReply(ReplyStatus.DONE, "шаг сделан")


class AskingPhrases(Phrases):
    """Шаг отмечает, а отвечает вопросом с кнопками — как Haiku в прогоне 02.11.2026."""

    def execute(self, phrase: str) -> AgentReply:
        super().execute(phrase)
        return AgentReply(ReplyStatus.CLARIFY, "Шаг сделан. Продолжить?", options=("Продолжай", "Пауза"))


class Delivered:
    def __init__(self) -> None:
        self.replies: list[AgentReply] = []

    def deliver(self, task: str, reply: AgentReply) -> None:
        self.replies.append(reply)


def run(plans: PlanBoard, phrases: Phrases) -> tuple[str, Delivered]:
    delivered = Delivered()
    plan = plans.find()
    assert plan is not None
    return PlanRun(plans, phrases, delivered, Unlocked()).run(plan.id), delivered  # pyright: ignore[reportArgumentType]


class TestRun:
    def test_plan_is_walked_to_the_end_one_phrase_per_step(self) -> None:
        plans = saved()

        outcome, delivered = run(plans, phrases := Phrases(plans))

        assert outcome == "План «Тесты модуля 1» пройден" and plans.all() == []
        assert len(phrases.phrases) == 3 and "сделай сам, без вопросов" in phrases.phrases[0]
        assert delivered.replies[-1].message == outcome      # итог — тоже уведомлением

    def test_question_after_a_done_step_is_delivered_as_done(self) -> None:
        """Журнал 02.11.2026: шаг сделан, а итог — «Продолжить?» с кнопками; ответить некому, прогон идёт сам."""
        plans = saved()

        outcome, delivered = run(plans, AskingPhrases(plans))

        assert outcome == "План «Тесты модуля 1» пройден"
        assert [(reply.status, reply.options) for reply in delivered.replies[:3]] == [(ReplyStatus.DONE, ())] * 3

    def test_step_that_does_not_move_stops_the_run(self) -> None:
        """Шаг вернул вопрос или ничего не отметил — второй раз то же не повторяется: ходить по кругу нельзя."""
        plans = saved()

        outcome, delivered = run(plans, phrases := Phrases(plans, AgentReply(ReplyStatus.CLARIFY, "Какой тест?")))

        assert outcome == "План «Тесты модуля 1» остановился на шаге 1: шаг не сдвинулся — Какой тест?"
        assert len(phrases.phrases) == 1 and delivered.replies[0].status is ReplyStatus.CLARIFY     # настоящий вопрос

    def test_awaiting_step_counts_as_movement(self) -> None:
        plans = saved()

        outcome, _ = run(plans, Phrases(plans, StepState.AWAITING))

        assert outcome.startswith("План «Тесты модуля 1» остановился на шаге 1")    # второй раз awaiting — уже круг

    def test_step_that_did_not_work_out_stops_the_run(self) -> None:
        """Журнал 29.10.2026: шаг отмечен «не вышло», а прогон пошёл дальше — решать, что с ним делать, должен человек."""
        plans = saved()

        outcome, _ = run(plans, phrases := Phrases(plans, StepState.FAILED))

        assert outcome == "План «Тесты модуля 1» остановлен на шаге 1: шаг сделан" and len(phrases.phrases) == 1

    @pytest.mark.parametrize("reply", [AgentReply(ReplyStatus.FAILED, "сбой"), AgentReply(ReplyStatus.STOPPED, "стоп")])
    def test_failure_or_stop_ends_the_run(self, reply: AgentReply) -> None:
        plans = saved()

        outcome, _ = run(plans, Phrases(plans, reply))

        assert outcome == f"План «Тесты модуля 1» остановлен на шаге 1: {reply.message}"

    def test_tool_starts_the_run_as_a_separate_launch(self) -> None:
        """Отдельный запуск, а не продолжение фразы: иначе он унаследовал бы её журнал и подтверждения."""
        plans, launched = saved(), Launched()
        program = Program("home", ("/venv/python", "-m", "jericho"), {}, Path("/c"), Path("/c"))

        result = execute(RunPlan(plans, launched, program), {})  # pyright: ignore[reportArgumentType]

        plan = plans.find()
        assert plan is not None and (result.ok, result.data["left"]) == (True, 3)
        assert launched.commands == [["env", "-u", "JERICHO_RUN", "-u", "JERICHO_DEADLINE", "/venv/python", "-m", "jericho", "plans", "--run", plan.id]]

    def test_finished_plan_is_not_started(self) -> None:
        plans = saved(["раз", "два"])
        plan = plans.find()
        assert plan is not None
        plan = plans.mark(plan, 1, StepState.DONE, "")
        plans.mark(plan, 2, StepState.FAILED, "кнопки нет")

        assert execute(RunPlan(plans, Launched(), Program("home", ("x",), {}, Path("/c"), Path("/c"))), {}).error == "plan_finished"  # pyright: ignore[reportArgumentType]


class Launched:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []

    def run(self, command: list[str], stdin: str | None = None, *, reads: bool = False, dry_answer: str = "") -> str:
        return ""

    def launch(self, command: list[str]) -> None:
        self.commands.append(list(command))


class TestTwoProcesses:
    """Окно на панели и прогон плана меняют план одновременно (ревью 02.11.2026, П3a №8)."""

    def test_marks_of_different_steps_both_survive(self, tmp_path: Path) -> None:
        store = JsonPlanStore(tmp_path / "plans.json")
        plan = board(store).create("утро", ["почта", "календарь"])
        seen_by_window = board(store).find(plan.id)       # окно прочитало план раньше
        assert seen_by_window is not None

        board(store).mark(plan, 2, StepState.DONE, "ок")         # прогон отметил второй шаг
        board(store).mark(seen_by_window, 1, StepState.FAILED, "нет сети")   # окно — первый, по старому объекту

        (kept,) = board(store).all()
        assert [step.state for step in kept.steps] == [StepState.FAILED, StepState.DONE]

    def test_a_held_lock_is_a_clear_refusal_not_a_lost_write(self, tmp_path: Path) -> None:
        held = FileLock(tmp_path / "plans.lock")
        assert held.acquire()
        busy = PlanBoard(MemoryList[Plan](), lambda: NOON, FileLock(tmp_path / "plans.lock"))

        with pytest.raises(StateBusy):
            busy.create("утро", ["почта"])
        held.release()


class TestLockThroughTheModule:
    """Ревью 07.11.2026, рекомендация: замок должен стоять в собранном модуле — `TestTwoProcesses` собирает доску сам."""

    def test_assembled_plans_wait_for_the_lock(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(PlansModule, "LOCK_WAIT", 0.05)
        core = fake_core(tmp_path, dry_run=False)
        module = PlansModule()
        own = SimpleNamespace(section=lambda name, section_class: PlansSettings(confirm_create=False))
        module.ready(cast(ModuleServices, SimpleNamespace(settings=own, core=core, program=None)))
        create = next(tool for tool in module.tools() if tool.name == "plan_create")
        held = FileLock(core.paths.state_dir / PlansModule.LOCK)
        assert held.acquire()
        try:
            result = execute(create, {"title": "утро", "steps": ["почта", "календарь"]})
        finally:
            held.release()

        assert result.error == "state_busy"


class Relaunch:
    def __init__(self, attended: bool) -> None:
        self.attended = attended
        self.launched: list[tuple[str, ...]] = []

    def unattended(self, *arguments: str) -> int:
        self.launched.append(arguments)
        return 0


class Run:
    def __init__(self) -> None:
        self.ran: list[str] = []

    def run(self, plan_id: str) -> str:
        self.ran.append(plan_id)
        return "готово"


class TestRunWithoutAPerson:
    """Сводка ревью 02.11.2026, №8: `plans --run` шёл с политикой «человек рядом» — EFFECT с `Approval.TOOL`
    проходил внутрь ручки, а вопросы ложились ждать «да». Как `task`: запуск заново с отметкой до сборки."""

    def test_run_by_a_person_relaunches_itself_unattended(self) -> None:
        relaunch, run = Relaunch(attended=True), Run()

        PlansCommand(board(), cast(PlanRun, run), relaunch).run(argparse.Namespace(close=None, run="p1"))

        assert relaunch.launched == [("plans", "--run", "p1")] and run.ran == []

    def test_the_relaunched_run_walks_the_plan(self) -> None:
        relaunch, run = Relaunch(attended=False), Run()

        PlansCommand(board(), cast(PlanRun, run), relaunch).run(argparse.Namespace(close=None, run="p1"))

        assert relaunch.launched == [] and run.ran == ["p1"]
