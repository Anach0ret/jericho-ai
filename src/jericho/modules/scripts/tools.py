"""Ручка `run_script`: голосом «Jericho, работа» — модель зовёт сценарий по имени, а не делает шаги сама."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, create_model

from jericho.core.tools.description import ToolDescription
from jericho.core.tools.request import ToolRequest
from jericho.core.tools.result import ToolRefusal, ToolResult
from jericho.core.tools.risk import Risk
from jericho.core.tools.tool import Tool
from jericho.modules.scripts.runner import ScriptRunner
from jericho.modules.scripts.settings import Script


class RunScriptRequest(ToolRequest):
    name: str


class RunScript(Tool[RunScriptRequest]):
    """Выполняет сценарий из настроек. Сценарий с шагом-фразой модели здесь не идёт: модель внутри вызова модели
    запустила бы ещё одну — такую фразу модель выполняет сама."""

    name = "run_script"
    risk = Risk.CHANGE        # шаги — ручки не выше CHANGE: сценарий с EFFECT не проходит проверку E014
    description = ToolDescription(
        when="пользователь называет сценарий по имени или явно просит его выполнить («работа», «запусти утро»).",
        does="выполняет шаги сценария по порядку без тебя: быстро и одинаково каждый раз. Не повторяй шаги сам.",
        returns='{"ok": true, "summary": итог словами} — перескажи итог; при сбое — на каком шаге и почему.',
        refusals=(
            "script_failed + summary (остановились на шаге — скажи, на каком); uses_model + steps (выполни шаги сам "
            "по порядку: tool — вызовом этой ручки с arguments, phrase — как поручение пользователя)."
        ),
    )

    def __init__(self, scripts: dict[str, Script], runner: ScriptRunner) -> None:
        self._scripts = scripts
        self._runner = runner
        names: Any = Literal[*scripts]  # pyright: ignore[reportInvalidTypeForm]
        listed = "; ".join(f"{name} — {script.title}" for name, script in scripts.items())
        self.request_type = create_model("RunScriptRequest", __base__=RunScriptRequest, name=(names, Field(description=f"Сценарий: {listed}.")))

    def _run(self, request: RunScriptRequest) -> ToolResult:
        script = self._scripts[request.name]
        if script.uses_model:
            # Все шаги и по порядку: раньше уходили только фразы, и шаг-ручка перед ними терялся (ревью П3a №11).
            steps = [{"phrase": step.phrase} if step.phrase else {"tool": step.tool, "arguments": step.arguments} for step in script.steps]
            raise ToolRefusal("uses_model", steps=steps)
        outcome = self._runner.run(request.name, script)
        if not outcome.ok:
            raise ToolRefusal("script_failed", summary=outcome.summary())
        return ToolResult.success(summary=outcome.summary())
