from collections.abc import Sequence
from pathlib import Path

import pytest

from jericho.core import ConfirmationGate, CoreServices, Paths, SkillConfig
from jericho.core.conf.loader import SettingsLoader
from jericho.core.skills.loader import SkillLoader, SkillLoadError
from jericho.core.skills.registry import InstalledSkills
from jericho.core.testing import Confirmations
from tests.core.sample_skills.notes.skill import AddNote, NotesSkill

SAMPLES = "tests.core.sample_skills"


class Runner:
    def run(
        self, command: Sequence[str], stdin: str | None = None, *, reads: bool = False, dry_answer: str = ""
    ) -> str:
        return ""

    def launch(self, command: Sequence[str]) -> None:
        self.run(command)


def core(tmp_path: Path) -> CoreServices:
    return CoreServices(Runner(), ConfirmationGate(Confirmations(), "run-1"), Paths(tmp_path / "state", tmp_path / "run"))


class Quiet(SkillConfig):
    name = "quiet"
    description = "Навык без ручек."


class Diary(NotesSkill):
    name = "diary"


class TestSkillLoader:
    def test_finds_the_skill_class_in_each_installed_package(self) -> None:
        skills = list(SkillLoader().load([f"{SAMPLES}.notes"]))

        assert [(type(skill), skill.name, skill.description) for skill in skills] == [
            (NotesSkill, "notes", "Заметки — записать мысль.")
        ]

    def test_skill_knows_its_own_directory(self) -> None:
        (skill,) = SkillLoader().load([f"{SAMPLES}.notes"])

        assert skill.directory == Path(__file__).parent / "sample_skills" / "notes"

    @pytest.mark.parametrize(
        ("package", "reason"),
        [
            (f"{SAMPLES}.missing", "module not found"),
            (f"{SAMPLES}.empty", "expected one SkillConfig subclass, found 0"),
            (f"{SAMPLES}.twins", "expected one SkillConfig subclass, found 2"),
            (f"{SAMPLES}.nameless", "name not set"),
        ],
    )
    def test_broken_skill_is_reported_with_its_module(self, package: str, reason: str) -> None:
        with pytest.raises(SkillLoadError, match=reason) as error:
            SkillLoader().load([package])

        assert package in str(error.value)

    def test_two_skills_cannot_share_a_name(self) -> None:
        with pytest.raises(SkillLoadError, match="skill names are not unique: notes"):
            SkillLoader().load([f"{SAMPLES}.notes", f"{SAMPLES}.notes"])


class TestInstalledSkills:
    def test_ready_hands_every_skill_its_own_settings_section_and_core_services(self, tmp_path: Path) -> None:
        skill, services = NotesSkill(), core(tmp_path)

        InstalledSkills([skill]).ready(SettingsLoader("tests.core.sample_settings", "Live").load(), services)

        assert skill.settings.tags == {"work": "работа"} and skill.core is services

    def test_collects_what_skills_give_to_the_core(self) -> None:
        skills = InstalledSkills([NotesSkill(), Quiet()])

        assert [type(tool) for tool in skills.tools()] == [AddNote]
        assert skills.contexts() == () and skills.commands() == ()

    def test_two_skills_cannot_share_a_tool_name(self) -> None:
        with pytest.raises(ValueError, match="tool names are not unique: add_note"):
            InstalledSkills([NotesSkill(), Diary()]).tools()


class TestPaths:
    def test_folders_follow_xdg(self, tmp_path: Path) -> None:
        paths = Paths.under_xdg("demo", {"XDG_STATE_HOME": str(tmp_path / "s"), "XDG_RUNTIME_DIR": str(tmp_path / "r")}, tmp_path)

        assert (paths.state_dir, paths.runtime_dir) == (tmp_path / "s" / "demo", tmp_path / "r" / "demo")

    def test_without_a_session_folder_the_runtime_files_live_next_to_the_state(self, tmp_path: Path) -> None:
        paths = Paths.under_xdg("demo", {}, tmp_path)

        assert paths.runtime_dir == tmp_path / ".local/state/demo/run"
