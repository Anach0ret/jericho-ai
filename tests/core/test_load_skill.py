from collections.abc import Sequence
from typing import Any

import pytest

from jericho.core import SkillConfig, Tool
from jericho.core.prompting.entities import Skill
from jericho.core.skills.guide import SkillGuides
from jericho.core.skills.load_skill import LoadSkill, brief_description
from jericho.core.skills.middleware import RequireLoadedSkill
from jericho.core.skills.registry import InstalledSkills
from jericho.core.tools.dispatcher import ToolDispatcher
from jericho.core.tools.middleware import Refusals
from jericho.core.tools.session import CallSession
from tests.core.sample_skills.notes.skill import AddNote, NotesSkill


class Folder:
    def values(self) -> dict[str, str]:
        return {"folder": "~/notes"}


class NotesWithContext(NotesSkill):
    def contexts(self) -> Sequence[Any]:
        return [Folder()]


class Diary(NotesSkill):
    name = "diary"

    def tools(self) -> Sequence[Any]:
        return []


class Quiet(SkillConfig):
    name = "quiet"
    description = "Навык без ручек."


class Source:
    def core(self) -> str:
        return "ЯДРО"

    def skill(self, name: str) -> Skill:
        return Skill(name, "Заметки.", ("add_note", "find_note"), "# Заметки\nПапка: {{folder}}.")


def phrase() -> tuple[ToolDispatcher, LoadSkill, Tool[Any]]:
    """Одна фраза: свой сеанс, ручка ядра и ручка навыка, как их видит сервер."""
    skills = InstalledSkills([NotesWithContext()])
    session = CallSession()
    dispatcher = ToolDispatcher([Refusals, RequireLoadedSkill], session)
    return dispatcher, LoadSkill(SkillGuides(Source(), skills), session, skills.names), skills.tools()[0]


class TestSkillGuide:
    def test_guide_is_the_skill_text_with_live_data_and_full_tool_descriptions(self) -> None:
        guide = SkillGuides(Source(), InstalledSkills([NotesWithContext()])).guide("notes")

        assert guide.startswith("# Заметки\nПапка: ~/notes.")
        assert "# РУЧКИ НАВЫКА\n\n## add_note\nКогда: Просят записать мысль." in guide

    def test_guide_names_tools_that_are_described_but_not_connected(self) -> None:
        guide = SkillGuides(Source(), InstalledSkills([NotesWithContext()])).guide("notes")

        assert "Ещё не подключены: find_note." in guide


class TestLoadSkill:
    def test_returns_the_guide_of_the_named_skill(self) -> None:
        dispatcher, load_skill, _ = phrase()

        result = dispatcher.call(load_skill, {"names": ["notes"]})

        guides = result.data["guides"]
        assert result.ok and isinstance(guides, dict) and list(guides) == ["notes"] and "Папка: ~/notes." in guides["notes"]

    def test_model_sees_which_skills_can_be_loaded(self) -> None:
        _, load_skill, _ = phrase()

        offered = load_skill.request_type.tool_schema()["properties"]["names"]

        assert offered["items"]["const"] == "notes" and offered["minItems"] == 1

    @pytest.mark.parametrize("arguments", [{"names": ["calendar"]}, {"names": []}, {"name": "notes"}])
    def test_unknown_skill_or_empty_list_is_a_wrong_parameter(self, arguments: dict[str, object]) -> None:
        dispatcher, load_skill, _ = phrase()

        assert dispatcher.call(load_skill, arguments).error == "invalid_parameters"

    def test_several_skills_are_loaded_by_one_call(self) -> None:
        skills = InstalledSkills([NotesWithContext(), Diary()])
        session = CallSession()
        dispatcher = ToolDispatcher([Refusals, RequireLoadedSkill], session)
        load_skill = LoadSkill(SkillGuides(Source(), skills), session, skills.names)

        result = dispatcher.call(load_skill, {"names": ["notes", "diary", "notes"]})

        guides = result.data["guides"]
        assert isinstance(guides, dict) and list(guides) == ["notes", "diary"]
        assert session.is_loaded("notes") and session.is_loaded("diary")
        assert load_skill.request_type.tool_schema()["properties"]["names"]["items"]["enum"] == ["notes", "diary"]


class TestRequireLoadedSkill:
    def test_skill_tool_is_refused_until_its_skill_is_loaded(self) -> None:
        dispatcher, _, add_note = phrase()

        result = dispatcher.call(add_note, {"text": "мысль"})

        assert result.to_dict() == {
            "ok": False, "error": "skill_not_loaded", "skill": "notes", "hint": 'сначала load_skill(names=["notes"])',
        }

    def test_after_loading_the_tool_works_for_the_rest_of_the_phrase(self) -> None:
        dispatcher, load_skill, add_note = phrase()

        dispatcher.call(load_skill, {"names": ["notes"]})

        assert dispatcher.call(add_note, {"text": "мысль"}).ok and dispatcher.call(add_note, {"text": "ещё"}).ok

    def test_core_tool_needs_no_skill(self) -> None:
        dispatcher, load_skill, _ = phrase()

        assert dispatcher.call(load_skill, {"names": ["notes"]}).ok

    def test_next_phrase_starts_with_nothing_loaded(self) -> None:
        dispatcher, load_skill, _ = phrase()
        dispatcher.call(load_skill, {"names": ["notes"]})
        next_dispatcher, _, add_note = phrase()

        assert next_dispatcher.call(add_note, {"text": "мысль"}).error == "skill_not_loaded"


class TestBriefDescription:
    def test_skill_tool_is_one_line_that_points_to_load_skill(self) -> None:
        _, _, add_note = phrase()

        brief = brief_description(add_note)

        assert brief.startswith("Ручка навыка `notes`.") and 'load_skill(names=["notes"])' in brief
        assert "Когда:" not in brief

    def test_core_tool_keeps_its_full_description(self) -> None:
        _, load_skill, _ = phrase()

        assert brief_description(load_skill) == load_skill.description.render()

    def test_tool_outside_any_skill_is_described_in_full(self) -> None:
        assert brief_description(AddNote()).startswith("Когда:")


class TestInstalledSkillsTools:
    def test_every_skill_tool_is_marked_with_its_skill_and_built_once(self) -> None:
        skills = InstalledSkills([NotesSkill(), Quiet()])

        assert [tool.skill for tool in skills.tools()] == ["notes"]
        assert skills.tools()[0] is skills.tools_of("notes")[0]

    def test_unknown_skill_is_an_error(self) -> None:
        with pytest.raises(KeyError):
            InstalledSkills([NotesSkill()]).get("calendar")
