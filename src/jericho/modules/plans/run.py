"""Прохождение плана без вопросов: каждый шаг — отдельной фразой «продолжай план», пока есть продвижение."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, ClassVar

from jericho.core.agent.entities import AgentReply, ReplyStatus
from jericho.core.jobs.entities import JobOutcome, JobStatus, JobTicket
from jericho.core.jobs.journal import JobJournal
from jericho.core.services.lock import ExclusiveLock
from jericho.core.services.output import Output
from jericho.modules.plans.board import PlanBoard
from jericho.modules.plans.entities import Plan, StepState

if TYPE_CHECKING:
    from jericho.core.agent.handle_phrase import HandlePhrase


class PlanRun:
    """Фраза за фразой, пока план не пройден. Стоп — шаг не вышел, человек занял ассистента или шаг не сдвинулся:
    ходить по кругу нельзя, а что делать дальше, решает человек."""

    PHRASE = "продолжай план «{title}» (id {id}): следующий шаг сделай сам, без вопросов, и отметь его"
    BUSY = "уже идёт: план проходит другой запуск"
    KIND = "plans"
    ENDED: ClassVar[dict[ReplyStatus, JobStatus]] = {ReplyStatus.FAILED: JobStatus.FAILED, ReplyStatus.STOPPED: JobStatus.STOPPED}

    def __init__(self, board: PlanBoard, handle_phrase: HandlePhrase, output: Output, lock: ExclusiveLock, jobs: JobJournal) -> None:
        self._board = board
        self._handle_phrase = handle_phrase
        self._output = output       # итоги шагов; итог всего прогона — через журнал работ
        self._lock = lock
        self._jobs = jobs

    def run(self, plan_id: str, job: str, continuation: str = "") -> JobOutcome:
        """Пройти план; итог — в журнал работ и уведомлением: пройден или где и почему остановился.
        Продолжение (`continuation`) — только если пройден весь план."""
        ticket = JobTicket(job, self.KIND, f"план {plan_id}", {"plan": plan_id}, continuation)
        return self._jobs.run(ticket, lambda: self._locked(plan_id))

    def _locked(self, plan_id: str) -> JobOutcome:
        if not self._lock.acquire():
            return JobOutcome.failed(self.BUSY)
        try:
            return self._steps(plan_id)
        finally:
            self._lock.release()

    def _steps(self, plan_id: str) -> JobOutcome:
        plan = self._board.find(plan_id)
        if plan is None:
            return JobOutcome.failed(f"плана {plan_id} нет")
        for _ in range(2 * len(plan.steps)):     # шаг может уйти на проверку и на само дело; больше — уже круг
            number = plan.next
            if number is None:
                summary = f"План «{plan.title}» без открытых шагов: {plan.finished} из {len(plan.steps)}"
                return JobOutcome(JobStatus.SUCCEEDED if plan.complete else JobStatus.FAILED, summary)
            before = self._progress(plan)
            phrase = self.PHRASE.format(title=plan.title, id=plan.id)
            reply = self._handle_phrase.execute(phrase)
            changed = self._board.find(plan_id)
            moved = changed is None or self._progress(changed) != before
            self._output.deliver(phrase, self._unasked(reply) if moved else reply)
            if reply == self._handle_phrase.busy:
                return JobOutcome.failed(f"План «{plan.title}» остановлен на шаге {number}: ассистент занят другой фразой")
            if reply.status in self.ENDED:
                return JobOutcome(self.ENDED[reply.status], f"План «{plan.title}» остановлен на шаге {number}: {reply.message}")
            if changed is None:      # пройденный план убирается сам; иначе его убрал человек
                last = sum(step.state.open for step in plan.steps) == 1
                return JobOutcome.succeeded(f"План «{plan.title}» пройден") if last else JobOutcome(JobStatus.STOPPED, f"План «{plan.title}» убран")
            step = changed.steps[number - 1]
            if step.state is StepState.FAILED:      # журнал 29.10.2026: после «не вышло» прогон шёл дальше
                return JobOutcome.failed(f"План «{plan.title}» остановлен на шаге {number}: {step.outcome or reply.message}")
            if self._progress(changed) == before:
                return self._stuck(plan, number, reply)
            plan = changed
        return JobOutcome.failed(f"План «{plan.title}» остановлен: запусков больше, чем вдвое против шагов")

    @staticmethod
    def _stuck(plan: Plan, number: int, reply: AgentReply) -> JobOutcome:
        """Шаг не сдвинулся. Вопрос модели или шаг, ждущий подтверждения, — ждём человека; иначе — не вышло."""
        step = plan.steps[number - 1]
        waiting = reply.status is ReplyStatus.CLARIFY or step.state is StepState.AWAITING
        summary = f"План «{plan.title}» остановился на шаге {number}: шаг не сдвинулся — {reply.message}"
        return JobOutcome(JobStatus.WAITING_USER if waiting else JobStatus.FAILED, summary)

    @staticmethod
    def _unasked(reply: AgentReply) -> AgentReply:
        """Вопрос в итоге сделанного шага («Продолжить?») — не вопрос: следующий шаг прогон берёт сам. Уведомление —
        без кнопок и не «ждёт ответа» (журнал 02.11.2026, модуль 8: шаги 3 и 4 — `clarify`). Шаг не сдвинулся —
        вопрос настоящий («Какой тест?») и уходит как есть."""
        if reply.status is not ReplyStatus.CLARIFY:
            return reply
        return replace(reply, status=ReplyStatus.DONE, options=())

    @staticmethod
    def _progress(plan: Plan) -> tuple[int, int | None, StepState | None]:
        """Что меняется, когда шаг сделан или проверен: сколько закрыто, какой следующий и в каком он состоянии."""
        step = plan.steps[plan.next - 1] if plan.next is not None else None
        return plan.finished, plan.next, step.state if step is not None else None
