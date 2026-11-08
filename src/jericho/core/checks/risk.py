"""Правило ручек: класс риска и то, кто спрашивает «да», выбраны явно."""

from __future__ import annotations

from typing import Any

from jericho.core.checks.base import CheckMessage, Project
from jericho.core.tools.allowlist import AllowlistTool
from jericho.core.tools.risk import Risk
from jericho.core.tools.tool import Tool


class RiskIsDeclared:
    """E008: каждая ручка навыка и модуля сама объявляет класс риска (`risk = Risk.…`), а не получает его по наследству от основы.

    Основа ручки считает необъявленный класс самым опасным, так что забытая строка ничего не открывает.
    Но класс читают модель и те, кто решает, что ассистенту можно, — он должен быть выбран, а не достаться случайно.
    """

    def run(self, project: Project) -> list[CheckMessage]:
        owners = [(skill.name, skill.tools()) for skill in project.skills]
        owners += [(f"модуль {module.name}", module.tools()) for module in project.modules]
        messages: list[CheckMessage] = []
        for owner, tools in owners:
            for tool in tools:
                if not self._declared(tool, "risk"):
                    text = f"ручка `{tool.name}` не объявила класс риска: добавь `risk = Risk.…` в её класс"
                    messages.append(CheckMessage("jericho.E008", owner, text))
                elif tool.risk is Risk.EFFECT and not isinstance(tool, AllowlistTool) and not self._declared(tool, "approval"):
                    text = (
                        f"ручка `{tool.name}` — EFFECT, но не сказала, кто спрашивает «да»: `approval = Approval.ASK` "
                        "(каркас, перед каждым вызовом) или `Approval.TOOL` (сама ручка, через ConfirmationGate)"
                    )
                    messages.append(CheckMessage("jericho.E008", owner, text))
        return messages

    @staticmethod
    def _declared(tool: Tool[Any], attribute: str) -> bool:
        own_classes = (cls for cls in type(tool).__mro__ if issubclass(cls, Tool) and cls is not Tool)
        return attribute in vars(tool) or any(attribute in vars(cls) for cls in own_classes)
