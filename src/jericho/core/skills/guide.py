"""Руководство навыка — то, что модель получает в ответ на `load_skill`."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from jericho.core.prompting.protocols import PromptSource
from jericho.core.prompting.template import render, values_of
from jericho.core.skills.registry import InstalledSkills
from jericho.core.tools.tool import Tool


class SkillGuides:
    """Собирает руководство навыка: его `SKILL.md` с живыми данными, полные описания его ручек и дополнения.

    Описания ручек второй раз нигде не пишутся — берутся из того же `ToolDescription`, что и в коде ручки.
    Дополнения — то, что о навыке знают модули ядра (например, заметки): приходят только с этим навыком,
    посторонние поручения за них не платят.
    """

    def __init__(self, source: PromptSource, skills: InstalledSkills, extras: Callable[[str], str] | None = None) -> None:
        self._source = source
        self._skills = skills
        self._extras = extras or (lambda skill: "")

    def guide(self, name: str, with_tools: bool = True) -> str:
        """Навыка с таким именем нет — KeyError: имя проверяется раньше, в запросе ручки.

        `with_tools=False` — без описаний ручек: для руководства в общем промпте, где ручки описаны сами.
        """
        skill = self._skills.get(name)
        text = self._source.skill(name)
        tools = self._skills.tools_of(name)
        listed = (self._tools(tools), self._missing(text.tools, tools)) if with_tools else ()
        parts = (render(text.body, values_of(skill.contexts())).strip(), *listed, self._extras(name))
        return "\n\n".join(part for part in parts if part)

    @staticmethod
    def _tools(tools: Sequence[Tool[Any]]) -> str:
        described = (f"## {tool.name}\n{tool.description.render()}" for tool in tools)
        return "\n\n".join(("# РУЧКИ НАВЫКА", *described))

    @staticmethod
    def _missing(described: Sequence[str], tools: Sequence[Tool[Any]]) -> str:
        connected = {tool.name for tool in tools}
        missing = [name for name in described if name not in connected]
        if not missing:
            return "Все ручки навыка подключены."
        return (
            f"Ещё не подключены: {', '.join(missing)}. Если для просьбы нужна одна из них — "
            "ответь `refused` и скажи, что это пока не умеешь."
        )
