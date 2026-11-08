"""Поиск навыков по списку `INSTALLED_SKILLS`."""

from __future__ import annotations

from collections.abc import Sequence

from jericho.core.discovery import PartLoader, repeated
from jericho.core.skills.config import SkillConfig
from jericho.core.skills.registry import InstalledSkills


class SkillLoadError(Exception):
    """Навык из списка не удалось подключить: нет `skill.py`, нет класса навыка или он описан не полностью."""


class SkillLoader:
    """Превращает список пакетов в навыки: в каждом пакете ищет `skill.py` и в нём один класс навыка."""

    _PARTS = PartLoader(SkillConfig, "skill", SkillLoadError, required=("name", "description"))

    def load(self, installed: Sequence[str]) -> InstalledSkills:
        skills = [self._PARTS.load(package) for package in installed]
        twice = repeated(skill.name for skill in skills)
        if twice:
            raise SkillLoadError(f"skill names are not unique: {', '.join(twice)}")
        return InstalledSkills(skills)
