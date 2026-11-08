import sys
from collections.abc import Iterator
from importlib import import_module
from pathlib import Path

import pytest

from jericho.core.checks.base import Project
from jericho.core.checks.structure import DEFAULT_CHECKS
from jericho.core.management.scaffold import Scaffold, ScaffoldError
from jericho.core.skills.loader import SkillLoader
from jericho.core.testing import execute


@pytest.fixture
def scaffold(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Scaffold]:
    """Заготовки создаются в настоящем пакете на диске, чтобы созданное можно было импортировать и проверить."""
    package = tmp_path / "sprouts"
    (package / "skills").mkdir(parents=True)
    (package / "__init__.py").touch()
    (package / "skills" / "__init__.py").touch()
    monkeypatch.syspath_prepend(str(tmp_path))
    yield Scaffold(package, "sprouts", "sprouts")
    for name in [name for name in sys.modules if name.startswith("sprouts")]:
        del sys.modules[name]


def findings(package_dir: Path, *packages: str) -> list[str]:
    skills = SkillLoader().load(packages)
    return [f"{message.code} {message.text}" for check in DEFAULT_CHECKS for message in check.run(Project(package_dir, skills))]


class TestStartSkill:
    def test_creates_the_standard_files(self, scaffold: Scaffold, tmp_path: Path) -> None:
        created = scaffold.skill("media", "Музыка и видео — пауза, следующий трек, громкость.")

        skill = tmp_path / "sprouts" / "skills" / "media"
        assert sorted(file.relative_to(skill).as_posix() for file in created) == [
            "SKILL.md", "__init__.py", "skill.py", "tests/__init__.py", "tests/test_skill.py", "tools/__init__.py",
        ]

    def test_new_skill_loads_and_passes_the_structure_checks(self, scaffold: Scaffold, tmp_path: Path) -> None:
        scaffold.skill("media", "Музыка и видео.")

        (skill,) = SkillLoader().load(["sprouts.skills.media"])

        assert (type(skill).__name__, skill.name, skill.description) == ("MediaSkill", "media", "Музыка и видео.")
        assert findings(tmp_path / "sprouts", "sprouts.skills.media") == []

    def test_new_skill_comes_with_a_test_that_passes(self, scaffold: Scaffold, tmp_path: Path) -> None:
        scaffold.skill("media", "Музыка и видео.")

        import_module("sprouts.skills.media.tests.test_skill").TestMediaSkill().test_skill_passes_the_structure_checks(tmp_path / "core")

    @pytest.mark.parametrize("name", ["Media", "2fast", "my-skill", "", "навык"])
    def test_name_must_be_a_plain_identifier(self, scaffold: Scaffold, name: str) -> None:
        with pytest.raises(ScaffoldError, match="имя"):
            scaffold.skill(name, "Описание.")

    @pytest.mark.parametrize("name", ["class", "import", "async"])
    def test_python_keywords_are_not_names(self, scaffold: Scaffold, name: str) -> None:
        """Подходит под образец имени, но `import ….class` не соберётся (ревью 02.11.2026, П4 №3)."""
        with pytest.raises(ScaffoldError, match="слово Python"):
            scaffold.skill(name, "Описание.")

    @pytest.mark.parametrize("description", ['Открывает "рабочий стол".', 'Путь C:\\new и """',"Две\nстроки."])
    def test_quotes_in_the_description_do_not_break_the_skill(self, scaffold: Scaffold, description: str) -> None:
        """Описание шло внутрь кавычек как есть: обычное «Открывает "рабочий стол"» давало SyntaxError (П1 №9)."""
        scaffold.skill("desk", description)

        (skill,) = SkillLoader().load(["sprouts.skills.desk"])

        assert skill.description == " ".join(description.split())

    def test_existing_skill_is_not_overwritten(self, scaffold: Scaffold) -> None:
        scaffold.skill("media", "Музыка.")

        with pytest.raises(ScaffoldError, match="уже есть"):
            scaffold.skill("media", "Другое.")

    def test_text_written_in_advance_is_kept(self, scaffold: Scaffold, tmp_path: Path) -> None:
        """У задуманного навыка может уже лежать `SKILL.md` — заготовка его не перезаписывает."""
        guide = tmp_path / "sprouts" / "skills" / "telegram" / "SKILL.md"
        guide.parent.mkdir()
        guide.write_text("---\ntools: [send_message]\n---\n\n# Сообщения\n", encoding="utf-8")

        created = scaffold.skill("telegram", "Сообщения.")

        assert guide not in created and guide.read_text(encoding="utf-8").endswith("# Сообщения\n")
        assert (guide.parent / "skill.py").exists()


class TestStartTool:
    def test_creates_a_working_tool_and_its_test(self, scaffold: Scaffold, tmp_path: Path) -> None:
        scaffold.skill("media", "Музыка.")

        created = scaffold.tool("media", "play_pause")

        skill = tmp_path / "sprouts" / "skills" / "media"
        assert [file.relative_to(skill).as_posix() for file in created] == [
            "tools/play_pause.py", "tests/test_play_pause.py", "SKILL.md",
        ]
        module = import_module("sprouts.skills.media.tools.play_pause")
        assert execute(module.PlayPause(), {"target": "пример"}).to_dict() == {"ok": True, "target": "пример"}

    def test_check_reminds_to_list_the_new_tool(self, scaffold: Scaffold, tmp_path: Path) -> None:
        scaffold.skill("media", "Музыка.")
        scaffold.tool("media", "play_pause")

        assert findings(tmp_path / "sprouts", "sprouts.skills.media") == ["jericho.E006 ручка `PlayPause` не вписана в `tools()`"]

    def test_new_tool_is_added_to_the_header_of_the_guide(self, scaffold: Scaffold, tmp_path: Path) -> None:
        guide = tmp_path / "sprouts" / "skills" / "media" / "SKILL.md"
        scaffold.skill("media", "Музыка.")

        scaffold.tool("media", "play_pause")
        scaffold.tool("media", "volume")

        assert guide.read_text(encoding="utf-8").startswith("---\ntools: [play_pause, volume]\n---\n\n# Навык: media")

    def test_guide_without_the_usual_header_is_left_alone(self, scaffold: Scaffold, tmp_path: Path) -> None:
        guide = tmp_path / "sprouts" / "skills" / "media" / "SKILL.md"
        scaffold.skill("media", "Музыка.")
        guide.write_text("# Музыка\nБез шапки.\n", encoding="utf-8")

        created = scaffold.tool("media", "play_pause")

        assert guide not in created and guide.read_text(encoding="utf-8") == "# Музыка\nБез шапки.\n"

    def test_tool_needs_an_existing_skill(self, scaffold: Scaffold) -> None:
        with pytest.raises(ScaffoldError, match="startskill calendar"):
            scaffold.tool("calendar", "add_event")

    def test_existing_tool_is_not_overwritten(self, scaffold: Scaffold) -> None:
        scaffold.skill("media", "Музыка.")
        scaffold.tool("media", "play_pause")

        with pytest.raises(ScaffoldError, match="уже есть"):
            scaffold.tool("media", "play_pause")


class TestServiceScaffold:
    def test_service_is_created_importable_and_provides_its_protocol(self, scaffold: Scaffold, tmp_path: Path) -> None:
        from jericho.core.checks.layers import ServiceImports
        from jericho.core.shared.config import ServiceLoader
        from jericho.core.skills.registry import InstalledSkills

        created = scaffold.service("mailbox")

        service = ServiceLoader().load(["sprouts.services.mailbox"])[0]
        protocol = import_module("sprouts.services.mailbox").Mailbox
        assert {file.name for file in created} >= {"service.py", "protocols.py", "testing.py", "local.py"}
        assert (service.name, service.provides.__name__) == ("mailbox", "provides")
        assert protocol.__name__ == "Mailbox"
        assert ServiceImports().run(Project(tmp_path / "sprouts", InstalledSkills([]))) == []

    def test_service_cannot_be_created_twice_or_with_a_wrong_name(self, scaffold: Scaffold) -> None:
        scaffold.service("mailbox")

        with pytest.raises(ScaffoldError, match="такая служба уже есть"):
            scaffold.service("mailbox")
        with pytest.raises(ScaffoldError, match="имя — латинские строчные буквы"):
            scaffold.service("Mail-Box")


class TestProjectScaffold:
    """Проект из образца собирается сразу: ни ключа, ни сети, ни правок руками."""

    @pytest.fixture
    def project(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
        from jericho.core.management.scaffold import ProjectScaffold

        ProjectScaffold(Path("/opt/jericho")).project("night-watch", tmp_path)
        monkeypatch.syspath_prepend(str(tmp_path / "night-watch" / "src"))
        yield tmp_path / "night-watch"
        for name in [name for name in sys.modules if name.startswith("night_watch")]:
            del sys.modules[name]

    def assembled(self, project: Path, tmp_path: Path) -> dict[str, object]:
        import logging

        from jericho.bootstrap import build_commands
        from jericho.core.assembly.installation import Installation

        logger = logging.getLogger("jericho")
        self._logging = (list(logger.handlers), logger.level, logger.propagate)
        environment = {
            Installation.SETTINGS_VARIABLE: "night_watch.settings",
            "XDG_STATE_HOME": str(tmp_path / "state"), "XDG_RUNTIME_DIR": str(tmp_path / "run"),
            "XDG_CONFIG_HOME": str(tmp_path / "config"),
        }
        return {command.name: command for command in build_commands(Installation.discover(environment, tmp_path, sys.executable))}

    @pytest.fixture(autouse=True)
    def restore_logging(self) -> Iterator[None]:
        import logging

        yield
        saved = getattr(self, "_logging", None)
        if saved is not None:
            logger = logging.getLogger("jericho")
            for handler in list(logger.handlers):
                logger.removeHandler(handler)
                handler.close()
            for handler in saved[0]:
                logger.addHandler(handler)
            logger.setLevel(saved[1])
            logger.propagate = saved[2]

    def test_project_has_everything_an_agent_needs_to_start(self, project: Path) -> None:
        files = {file.relative_to(project).as_posix() for file in project.rglob("*") if file.is_file()}

        assert {
            "AGENTS.md", "README.md", "pyproject.toml", ".gitignore", ".githooks/pre-commit", "tests/test_project.py", "docs/decisions.md",
            "src/night_watch/__main__.py", "src/night_watch/settings/base.py", "src/night_watch/settings/prompt/role.md",
            "src/night_watch/settings/script.yaml", "src/night_watch/services/README.md", "src/night_watch/skills/__init__.py",
        } <= files
        assert 'night_watch = "night_watch.__main__:main"' in (project / "pyproject.toml").read_text(encoding="utf-8")
        assert 'jericho-ai = { path = "/opt/jericho", editable = true }' in (project / "pyproject.toml").read_text(encoding="utf-8")

    @pytest.mark.skipif(sys.platform == "win32", reason="бит исполнения — POSIX; на Windows хук запускает git")
    def test_hook_is_executable(self, project: Path) -> None:
        assert (project / ".githooks/pre-commit").stat().st_mode & 0o111

    def test_new_project_is_assembled_and_passes_its_own_checks(self, project: Path, tmp_path: Path) -> None:
        import argparse

        commands = self.assembled(project, tmp_path)

        commands["check"].run(argparse.Namespace())  # pyright: ignore[reportAttributeAccessIssue]
        assert {"ask", "check", "startskill", "starttool", "startservice", "log"} <= set(commands)
        assert not set(commands) & {"listen", "notes", "mcp"}      # ни голоса, ни заметок, ни программы claude

    def test_new_project_answers_a_task_without_a_model(self, project: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        import argparse

        self.assembled(project, tmp_path)["ask"].run(argparse.Namespace(phrase="привет"))  # pyright: ignore[reportAttributeAccessIssue]

        assert capsys.readouterr().out.startswith("[done] Ассистент night-watch собран")

    def test_empty_folder_made_beforehand_is_filled(self, tmp_path: Path) -> None:
        """Папку заводят заранее (и даже `git init` в ней) — проект создаётся в ней же."""
        from jericho.core.management.scaffold import ProjectScaffold

        (tmp_path / "night-guard" / ".git").mkdir(parents=True)

        created = ProjectScaffold().project("night-guard", tmp_path)

        assert (tmp_path / "night-guard" / "AGENTS.md") in created

    def test_project_outside_the_sources_takes_the_framework_from_git_by_its_version(self, tmp_path: Path) -> None:
        """В PyPI под именем `jericho` чужой пакет: зависимость без адреса поставила бы его."""
        from jericho.core.management.scaffold import ProjectScaffold

        ProjectScaffold(repository="https://github.com/me/jericho", version="9.9.9").project("night-owl", tmp_path)

        pyproject = (tmp_path / "night-owl" / "pyproject.toml").read_text(encoding="utf-8")
        assert '"jericho-ai @ git+https://github.com/me/jericho@v9.9.9",' in pyproject and "tool.uv.sources" not in pyproject

    def test_project_goes_into_the_current_empty_folder_when_asked(self, tmp_path: Path) -> None:
        """`startproject имя .` — как у Django: папку завели заранее и в ней же и создают проект."""
        from jericho.core.management.scaffold import ProjectScaffold

        here = tmp_path / "night-guard"
        here.mkdir()

        ProjectScaffold().project("night-guard", here, directory=here)

        assert (here / "AGENTS.md").exists() and not (here / "night-guard").exists()

    def test_occupied_place_and_wrong_name_are_refused(self, project: Path, tmp_path: Path) -> None:
        from jericho.core.management.scaffold import ProjectScaffold

        with pytest.raises(ScaffoldError, match="папка не пуста"):
            ProjectScaffold().project("night-watch", tmp_path)
        with pytest.raises(ScaffoldError, match="имя — латинские строчные буквы"):
            ProjectScaffold().project("Night Watch", tmp_path)
        with pytest.raises(ScaffoldError, match="слово Python"):
            ProjectScaffold().project("class", tmp_path)
