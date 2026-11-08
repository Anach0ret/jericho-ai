"""Навык, в котором нарушено каждое правило структуры, — образец для тестов `jericho check`."""

from collections.abc import Sequence
from typing import Any

from jericho.core import SkillConfig, Tool
from tests.core.sample_skills.messy.tools.listed import Listed


class MessySkill(SkillConfig):
    name = "messy"
    description = "Беспорядок."

    def tools(self) -> Sequence[Tool[Any]]:
        return [Listed()]
