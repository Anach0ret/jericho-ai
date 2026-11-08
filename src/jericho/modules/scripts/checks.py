"""Правило сценариев: опечатка в сценарии видна в `check`, а не когда нажали кнопку."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from jericho.core.checks.base import CheckMessage, Project
from jericho.core.tools.risk import Risk
from jericho.core.tools.tool import Tool
from jericho.modules.scripts.settings import ScriptsSettings


class ScriptsAreValid:
    """E014: каждый шаг-ручка сценария называет существующую ручку, его параметры проходят её схему, и класс ручки
    не EFFECT — «да» на каждое такое действие спрашивают у человека, а сценарий идёт без вопросов."""

    CODE = "jericho.E014"

    def run(self, project: Project) -> list[CheckMessage]:
        if project.settings is None:
            return []
        scripts = project.settings.section("scripts", ScriptsSettings).items
        tools: dict[str, Tool[Any]] = {tool.name: tool for skill in project.skills for tool in skill.tools()}
        tools |= {tool.name: tool for module in project.modules for tool in module.tools()}
        messages: list[CheckMessage] = []
        for name, script in scripts.items():
            for number, step in enumerate(script.steps, 1):
                if step.tool:
                    problem = self._problem(tools.get(step.tool), step.tool, step.arguments)
                    if problem:
                        messages.append(CheckMessage(self.CODE, f"scripts.{name}", f"шаг {number}: {problem}"))
        return messages

    @staticmethod
    def _problem(tool: Tool[Any] | None, name: str, arguments: dict[str, Any]) -> str:
        if tool is None:
            return f"ручки `{name}` нет ни у одного навыка или модуля"
        if tool.risk is Risk.EFFECT:
            return f"`{name}` — EFFECT: в сценарии без «да» ей не место; такое действие — фразой для модели"
        try:
            tool.request_type.model_validate(arguments)
        except ValidationError as error:
            fields = ", ".join(".".join(map(str, item["loc"])) or "(параметры)" for item in error.errors())
            return f"параметры `{name}` не проходят её схему: {fields}"
        return ""
