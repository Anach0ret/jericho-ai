import sys
import time
from dataclasses import replace
from pathlib import Path

import pytest

from jericho.bootstrap import build_commands
from jericho.core.agent.active_backend import ActiveBackend
from jericho.core.assembly.agent import build_agent
from jericho.core.assembly.installation import Installation, InstallationError
from jericho.core.assembly.modules import load_modules, ready_modules
from jericho.core.assembly.skills import build_skills
from jericho.core.assembly.state import build_state
from jericho.core.assembly.tools import build_toolset
from jericho.core.services.paths import UserDirs
from jericho.core.services.phrase_deadline import PhraseDeadline


class TestBootstrap:
    def test_whole_application_is_assembled_into_commands(self, installation: Installation) -> None:
        names = [command.name for command in build_commands(installation)]

        assert names[:2] == ["ask", "prompt"]
        assert {"log", "check", "stop", "startskill", "starttool", "mcp", "add-note"} <= set(names)   # команды ядра, бэкенда и ручки
        assert not set(names) & {"listen", "notes"}      # голос и заметки — модули: проект без них о них не знает
        assert len(names) == len(set(names))

    def test_state_goes_where_the_environment_says(self, installation: Installation, tmp_path: Path) -> None:
        build_commands(installation)

        assert (tmp_path / "state" / "jericho" / "journal.jsonl").exists()

    @pytest.mark.skipif(sys.platform == "win32", reason="права 0700/0600 — договор POSIX; на Windows — профиль пользователя (E015)")
    def test_state_is_closed_to_other_users_of_the_machine(self, installation: Installation, tmp_path: Path) -> None:
        """В папках разговор, заметки и журнал с фразами; папка, созданная раньше открытой, тоже закрывается."""
        earlier = tmp_path / "state" / "jericho"
        earlier.mkdir(parents=True, mode=0o775)
        (earlier / "journal.jsonl").touch(mode=0o664)

        build_commands(installation)

        modes = [path.stat().st_mode & 0o777 for path in (earlier, tmp_path / "run" / "jericho", earlier / "journal.jsonl")]
        assert modes == [0o700, 0o700, 0o600]

    def test_tool_server_is_started_the_same_way_and_for_the_same_project(self, installation: Installation) -> None:
        assert installation.launch == (sys.executable, "-m", "jericho")
        assert installation.environment_for("Eval") == {
            "JERICHO_SETTINGS_MODULE": "tests.core.sample_settings", "JERICHO_CONFIGURATION": "Eval",
        }

    def test_tool_server_works_in_the_run_of_the_phrase_that_started_it(self, installation: Installation) -> None:
        """Иначе вызовы ручек в журнале не связать со своей фразой."""
        phrase = build_state(installation.settings(), installation)
        child = {**installation.environment, **installation.tool_server_environment(phrase.run_id)}
        server = build_state(installation.settings(), replace(installation, environment=child))

        assert server.run_id == phrase.run_id
        assert build_state(installation.settings(), installation).run_id != phrase.run_id     # новая фраза — новый запуск

    def test_tool_server_keeps_the_deadline_of_the_phrase_that_started_it(self, installation: Installation) -> None:
        """Критика плана 07.11.2026, риск 1: сервер ручек звал диспетчер без срока — после конца фразы ручка выполнялась."""
        child = {**installation.environment, PhraseDeadline.VARIABLE: repr(time.time() - 1)}
        server = build_state(installation.settings(), replace(installation, environment=child))

        assert server.phrase_deadline.passed()
        assert not build_state(installation.settings(), installation).phrase_deadline.passed()     # фраза ставит срок сама

    def test_variant_of_settings_comes_from_the_environment(self, installation: Installation) -> None:
        assert installation.configuration == "Live"
        assert replace(installation, environment={"JERICHO_CONFIGURATION": "DryRun"}).configuration == "DryRun"


class TestProject:
    """Каркас узнаёт о проекте из окружения и ничего не считает от собственной папки, кроме своих текстов."""

    def discover(self, tmp_path: Path, settings_module: str) -> Installation:
        environment = {
            Installation.SETTINGS_VARIABLE: settings_module,
            "XDG_STATE_HOME": str(tmp_path / "state"),
            "XDG_RUNTIME_DIR": str(tmp_path / "run"),
        }
        return Installation.discover(environment, tmp_path, sys.executable)

    def test_everything_about_the_project_follows_from_its_settings_module(self, tmp_path: Path) -> None:
        home = self.discover(tmp_path, "home.settings")

        assert (home.project_package, home.skills_package) == ("home", "home.skills")
        config = UserDirs.find({}, tmp_path).config / "home"      # папка настроек по правилам ОС (на Linux ~/.config)
        assert home.machine_files == (config / "local.toml", config / "secrets.toml")

    def test_machine_files_can_live_where_the_environment_says(self, tmp_path: Path) -> None:
        """Проект может называться иначе, чем папка его настроек: переезд проекта не трогает файлы машины."""
        environment = {Installation.SETTINGS_VARIABLE: "home.settings", Installation.CONFIG_VARIABLE: str(tmp_path / "cfg")}
        home = Installation.discover(environment, tmp_path, sys.executable)

        assert home.machine_files == (tmp_path / "cfg/local.toml", tmp_path / "cfg/secrets.toml")
        assert home.environment_for("Live")[Installation.CONFIG_VARIABLE] == str(tmp_path / "cfg")

    def test_framework_knows_about_itself_only_where_its_own_texts_lie(self, installation: Installation) -> None:
        assert installation.core_evals.exists()

    def test_assistant_built_on_modules_gets_what_they_bring(self, tmp_path: Path) -> None:
        """Тот же каркас, другой вариант настроек: с модулями появляются их команды и ручки."""
        environment = {
            Installation.SETTINGS_VARIABLE: "tests.core.sample_settings",
            Installation.CONFIGURATION_VARIABLE: "WithMemory",
            "XDG_STATE_HOME": str(tmp_path / "state"),
            "XDG_RUNTIME_DIR": str(tmp_path / "run"),
        }

        names = {command.name for command in build_commands(Installation.discover(environment, tmp_path, sys.executable))}

        assert {"notes", "add-note", "task", "due", "timers"} <= names and "listen" not in names

    def test_tool_server_of_two_model_programs_is_one_command(self, tmp_path: Path) -> None:
        """`claude_cli` и запасной `codex_cli` поднимают один и тот же сервер ручек: команда `mcp` — одна."""
        environment = {
            Installation.SETTINGS_VARIABLE: "tests.core.sample_settings",
            Installation.CONFIGURATION_VARIABLE: "WithCodexFallback",
            "XDG_STATE_HOME": str(tmp_path / "state"),
            "XDG_RUNTIME_DIR": str(tmp_path / "run"),
        }

        names = [command.name for command in build_commands(Installation.discover(environment, tmp_path, sys.executable))]

        assert names.count("mcp") == 1 and len(names) == len(set(names))

    def test_project_that_is_not_named_is_an_error_that_says_what_to_do(self, tmp_path: Path) -> None:
        with pytest.raises(InstallationError, match="JERICHO_SETTINGS_MODULE is not set"):
            Installation.discover({}, tmp_path, sys.executable)

    def test_project_whose_package_cannot_be_imported_is_named(self, tmp_path: Path) -> None:
        with pytest.raises(InstallationError, match="nowhere: the package of the assistant is not importable"):
            _ = self.discover(tmp_path, "nowhere.settings").project_dir

    def test_the_main_backend_is_known_to_the_policy_of_private_data(self, tmp_path: Path) -> None:
        """Без `agent.private_backends` личные данные — только основному: и в процессе фразы, и в сервере ручек."""
        environment = {
            Installation.SETTINGS_VARIABLE: "tests.core.sample_settings",
            Installation.CONFIGURATION_VARIABLE: "WithCodexFallback",
            "XDG_STATE_HOME": str(tmp_path / "state"),
            "XDG_RUNTIME_DIR": str(tmp_path / "run"),
        }
        installation = Installation.discover(environment, tmp_path, sys.executable)
        settings = installation.settings()
        state = build_state(settings, installation)
        modules = load_modules(settings)
        skills = build_skills(settings, state, modules)
        ready_modules(modules, settings, state, skills.installed, installation)

        build_agent(settings, skills, modules, build_toolset(settings, skills, modules, state), state, installation)
        server = ActiveBackend.from_environment({ActiveBackend.VARIABLE: "codex_cli", ActiveBackend.MAIN_VARIABLE: "claude_cli"})

        assert state.active_backend.main == "claude_cli" and (server.name, server.main) == ("codex_cli", "claude_cli")

    def test_one_name_is_one_tool_across_core_modules_and_skills(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Ручка модуля с именем ручки навыка: каталог брал первую, сервер ручек — последнюю (ревью 02.11.2026, П1 №7)."""
        environment = {
            Installation.SETTINGS_VARIABLE: "tests.core.sample_settings",
            "XDG_STATE_HOME": str(tmp_path / "state"),
            "XDG_RUNTIME_DIR": str(tmp_path / "run"),
        }
        installation = Installation.discover(environment, tmp_path, sys.executable)
        settings = installation.settings()
        state = build_state(settings, installation)
        modules = load_modules(settings)
        skills = build_skills(settings, state, modules)
        (skill_tool,) = [tool for tool in skills.installed.tools() if tool.name == "add_note"]
        monkeypatch.setattr(modules, "tools", lambda: (type(skill_tool)(),))

        with pytest.raises(ValueError, match="add_note: ядро или модуль, навык notes"):
            build_toolset(settings, skills, modules, state)
