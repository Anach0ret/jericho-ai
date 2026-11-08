"""Подключённые навыки как одно целое."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import TYPE_CHECKING, Any

from jericho.core.conf.settings import Settings
from jericho.core.discovery import repeated
from jericho.core.management.base import Command
from jericho.core.prompting.protocols import PromptContext
from jericho.core.services.core_services import CoreServices
from jericho.core.shared.registry import ServiceError
from jericho.core.skills.config import SkillConfig
from jericho.core.tools.tool import Tool

if TYPE_CHECKING:
    from jericho.core.checks.base import Check


class InstalledSkills:
    """Навыки из `INSTALLED_SKILLS` в порядке списка: собирает их и складывает то, что они отдают ядру."""

    def __init__(self, skills: Sequence[SkillConfig[Any]]) -> None:
        self._skills = tuple(skills)
        self._tools: dict[str, tuple[Tool[Any], ...]] | None = None

    def __iter__(self) -> Iterator[SkillConfig[Any]]:
        return iter(self._skills)

    def ready(self, settings: Settings, core: CoreServices) -> None:
        """Каждый навык получает только свой раздел настроек. Навык, которому не хватает службы, не собирается."""
        for skill in self._skills:
            missing = [protocol.__name__ for protocol in skill.requires if not core.shared.has(protocol)]
            if missing:
                raise ServiceError(
                    f"skill {skill.name}: requires service {', '.join(missing)} — add the package that provides it "
                    "to INSTALLED_SERVICES"
                )
            skill.ready(settings.skill(skill.name, skill.settings_class), core)

    def get(self, name: str) -> SkillConfig[Any]:
        """Навык по имени; такого нет — KeyError."""
        for skill in self._skills:
            if skill.name == name:
                return skill
        raise KeyError(name)

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(skill.name for skill in self._skills)

    def tools(self) -> tuple[Tool[Any], ...]:
        """Ручки всех навыков. Каждая помечена именем своего навыка."""
        return tuple(tool for name in self.names for tool in self.tools_of(name))

    def tools_of(self, name: str) -> tuple[Tool[Any], ...]:
        return self._tools_by_skill()[name]

    def _tools_by_skill(self) -> dict[str, tuple[Tool[Any], ...]]:
        """Навык собирает свои ручки один раз: и список для модели, и руководство навыка говорят об одних объектах."""
        if self._tools is None:
            self._tools = {skill.name: tuple(skill.tools()) for skill in self._skills}
            for name, tools in self._tools.items():
                for tool in tools:
                    tool.skill = name
            twice = repeated(tool.name for tools in self._tools.values() for tool in tools)
            if twice:
                raise ValueError(f"tool names are not unique: {', '.join(twice)}")
        return self._tools

    def contexts(self) -> tuple[PromptContext, ...]:
        return tuple(context for skill in self._skills for context in skill.contexts())

    def commands(self) -> tuple[Command, ...]:
        return tuple(command for skill in self._skills for command in skill.commands())

    def checks(self) -> tuple[Check, ...]:
        return tuple(check for skill in self._skills for check in skill.checks())
