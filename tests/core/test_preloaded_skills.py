"""PRELOADED_SKILLS: руководство навыка — в общем промпте, `load_skill` для него не нужен (минус ход модели)."""

from types import SimpleNamespace
from typing import Any, cast

import pytest

from jericho.core.assembly.skills import preload_skills
from jericho.core.prompting.builder import PromptBuilder
from jericho.core.skills.load_skill import brief_description
from jericho.core.skills.loader import SkillLoadError
from jericho.core.skills.registry import InstalledSkills
from jericho.core.testing import Source
from jericho.core.tools.session import CallSession
from tests.core.sample_skills.notes.skill import NotesSkill


def installed() -> InstalledSkills:
    skills = InstalledSkills([NotesSkill()])
    skills.tools()      # ручки собираются и помечаются именем навыка
    return skills


class TestPreloadedSkills:
    def test_preloaded_skill_is_loaded_and_its_tools_are_described_in_full(self) -> None:
        skills, session = installed(), CallSession()

        preload_skills(skills, ("notes",), cast(Any, SimpleNamespace(session=session)))

        tool = skills.tools_of("notes")[0]
        assert session.is_loaded("notes") and tool.in_prompt
        assert brief_description(tool) == tool.description.render()      # не «сначала вызови load_skill»

    def test_unknown_name_is_an_error_that_says_what_to_name(self) -> None:
        with pytest.raises(SkillLoadError, match="skill names, not packages"):
            preload_skills(installed(), ("tests.core.sample_skills.notes",), cast(Any, SimpleNamespace(session=CallSession())))

    def test_guide_goes_into_the_prompt_and_the_index_says_so(self) -> None:
        prompt = PromptBuilder(Source(), (), ["desktop"], guide=lambda name: f"ПРАВИЛА {name}", preloaded=["desktop"]).build()

        assert "РУКОВОДСТВО НАВЫКА desktop\nПРАВИЛА desktop" in prompt
        assert f"**desktop** — рабочий стол ({PromptBuilder.PRELOADED})" in prompt

    def test_not_preloaded_stays_as_before(self) -> None:
        prompt = PromptBuilder(Source(), (), ["desktop"]).build()

        assert "РУКОВОДСТВО НАВЫКА" not in prompt and PromptBuilder.PRELOADED not in prompt
