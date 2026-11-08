"""Выполнение сценария: шаги по порядку, каждый — через диспетчер (ручка) или через модель (фраза)."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from jericho.core.agent.entities import AgentReply, ReplyStatus
from jericho.core.tools.catalog import ToolCatalog
from jericho.modules.scripts.settings import Script

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class StepOutcome:
    label: str
    ok: bool
    detail: str = ""
    waiting: bool = False      # шаг-фраза кончилась вопросом модели («зарегистрировать?»): ждём человека, это не сбой


@dataclass(frozen=True, slots=True)
class ScriptOutcome:
    name: str
    title: str
    steps: tuple[StepOutcome, ...] = field(default=())
    total: int = 0          # сколько шагов в сценарии: выполненных может быть меньше — остановились на сбое

    @property
    def ok(self) -> bool:
        return len(self.steps) == self.total and all(step.ok for step in self.steps)

    @property
    def waiting(self) -> bool:
        return bool(self.steps) and self.steps[-1].waiting

    def summary(self) -> str:
        """Итог словами: что сделано, а если остановились — на каком шаге и почему."""
        if self.ok:
            details = "; ".join(step.detail for step in self.steps if step.detail)
            return f"Готово: {self.title}" + (f" — {details}" if details else "")
        failed = self.steps[-1]
        if failed.waiting:
            return f"Ждёт ответа: {self.title} — {failed.detail}"
        done = len(self.steps) - 1
        return f"Не до конца: {self.title} — шаг {done + 1} из {self.total} ({failed.label}): {failed.detail or 'не получилось'}"


class ScriptRunner:
    """Шаги по порядку, на первом сбое — стоп: дальше шли бы шаги, рассчитанные на сделанный предыдущий.

    Ручки вызываются тем же диспетчером, что и у модели (`ToolCatalog.call`): слои, политика риска, журнал —
    у сценария не больше прав, чем у фразы. Фраза уходит модели (`ask`); без `ask` — только сценарии без фраз.
    """

    def __init__(self, catalog: ToolCatalog, ask: Callable[[str], AgentReply] | None = None) -> None:
        self._catalog = catalog
        self._ask = ask

    def run(self, name: str, script: Script) -> ScriptOutcome:
        outcomes: list[StepOutcome] = []
        for step in script.steps:
            outcome = self._tool(step.tool, step.arguments) if step.tool else self._phrase(step.label, step.phrase)
            outcomes.append(outcome)
            if not outcome.ok:
                break
        result = ScriptOutcome(name, script.title, tuple(outcomes), len(script.steps))
        logger.info("script", extra={"data": {
            "script": name, "title": script.title, "ok": result.ok, "waiting": result.waiting, "summary": result.summary(),
            "steps": [{"step": step.label, "ok": step.ok, "detail": step.detail} for step in outcomes],
        }})
        return result

    def _tool(self, tool: str, arguments: dict[str, object]) -> StepOutcome:
        try:
            result = self._catalog.call(tool, arguments)
        except LookupError:
            return StepOutcome(tool, False, f"нет ручки {tool}")
        if result.ok:
            detail = result.data.get("detail")
            return StepOutcome(tool, True, detail if isinstance(detail, str) else "")
        return StepOutcome(tool, False, str(result.data.get("detail") or result.error))

    def _phrase(self, label: str, phrase: str) -> StepOutcome:
        if self._ask is None:
            return StepOutcome(label, False, "шаг-фраза идёт модели — такой сценарий запускают командой или кнопкой, а не голосом")
        reply = self._ask(phrase)
        return StepOutcome(label, reply.status is ReplyStatus.DONE, reply.message, waiting=reply.status is ReplyStatus.CLARIFY)
