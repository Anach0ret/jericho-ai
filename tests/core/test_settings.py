from pathlib import Path

import pytest
from pydantic import ValidationError

from jericho.backends.claude_cli.settings import ClaudeSettings
from jericho.core.conf.loader import SettingsError, SettingsLoader
from jericho.core.conf.settings import Settings, SkillSettings
from tests.core.sample_settings import NotesSettings

MODULE = "tests.core.sample_settings"


def claude(settings: Settings) -> ClaudeSettings:
    """Раздел бэкенда — пример раздела, который приносит не ядро."""
    return settings.section("claude_cli", ClaudeSettings)


def write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


class TestSettingsLoader:
    def test_project_class_overrides_core_defaults(self) -> None:
        settings = SettingsLoader(MODULE, "Live").load()

        assert (claude(settings).model, settings.agent.timeout) == ("sonnet", 90.0)
        assert settings.INSTALLED_SKILLS == ("tests.core.sample_skills.notes",)

    def test_configuration_is_chosen_by_name(self) -> None:
        assert SettingsLoader(MODULE, "Quiet").load().agent.timeout == 10

    def test_unknown_configuration_lists_the_available_ones(self) -> None:
        with pytest.raises(SettingsError, match="no configuration 'Prod', available: Base, Live, Quiet, Rehearsal, SharedRehearsal, WithCodexFallback, WithMemory$"):
            SettingsLoader(MODULE, "Prod").load()

    def test_dry_run_gets_its_own_state_folder(self) -> None:
        assert SettingsLoader(MODULE, "Rehearsal").load().state_name == "jericho-rehearsal"

    def test_dry_run_sharing_state_with_a_working_configuration_does_not_load(self) -> None:
        """Иначе пробный вопрос, заметка и разговор попали бы в настоящие."""
        with pytest.raises(SettingsError, match="SharedRehearsal: dry_run shares state_name 'jericho' with Base, Live, Quiet, WithCodexFallback, WithMemory"):
            SettingsLoader(MODULE, "SharedRehearsal").load()

    def test_machine_file_cannot_point_dry_run_back_at_the_working_state(self, tmp_path: Path) -> None:
        local = write(tmp_path / "local.toml", 'state_name = "jericho"\n')

        with pytest.raises(SettingsError, match="shares state_name"):
            SettingsLoader(MODULE, "Rehearsal", [local]).load()

    def test_shared_machine_file_cannot_merge_working_and_dry_state(self, tmp_path: Path) -> None:
        """Общий файл машины даёт одно state_name всем вариантам: сравнивать надо итог, а не умолчания классов (R07)."""
        local = write(tmp_path / "local.toml", 'state_name = "shared"\n')

        with pytest.raises(SettingsError, match="shares state_name 'shared' with Base, Live"):
            SettingsLoader(MODULE, "Rehearsal", [local]).load()

    @pytest.mark.parametrize("name", ["jericho/.", "./jericho", "../jericho", "a/b", "", ".", "..", ".hidden", "~/x"])
    def test_state_name_is_one_plain_folder_name(self, name: str) -> None:
        """Ревью 02.11.2026, сводка №6: Live `same` и Eval `same/.` — разные строки, а папка одна; проверка их пропускала."""
        with pytest.raises(ValidationError, match="state_name"):
            Settings(state_name=name)

    def test_the_trick_does_not_load_through_a_machine_file(self, tmp_path: Path) -> None:
        local = write(tmp_path / "local.toml", 'state_name = "jericho/."\n')

        with pytest.raises(SettingsError, match="state_name"):
            SettingsLoader(MODULE, "Rehearsal", [local]).load()

    def test_machine_file_overrides_only_what_it_names(self, tmp_path: Path) -> None:
        local = write(tmp_path / "local.toml", '[claude_cli]\nclaude = "~/.local/bin/claude"\n\n[notes.tags]\nhome = "дом"\n')

        settings = SettingsLoader(MODULE, "Live", [local]).load()

        assert claude(settings).claude == Path.home() / ".local/bin/claude"
        assert claude(settings).model == "sonnet"
        assert settings.skill("notes", NotesSettings).tags == {"work": "работа", "home": "дом"}

    def test_later_file_wins(self, tmp_path: Path) -> None:
        local = write(tmp_path / "local.toml", '[claude_cli]\nmodel = "opus"\n')
        secrets = write(tmp_path / "secrets.toml", '[claude_cli]\nmodel = "haiku"\n')

        assert claude(SettingsLoader(MODULE, "Live", [local, secrets]).load()).model == "haiku"

    def test_missing_file_is_skipped(self, tmp_path: Path) -> None:
        assert claude(SettingsLoader(MODULE, "Live", [tmp_path / "local.toml"]).load()).model == "sonnet"

    @pytest.mark.parametrize(
        ("text", "problem"),
        [
            ('[claude_cli]\nmodle = "opus"\n', "claude_cli.modle: Extra inputs are not permitted"),
            ('[agent]\ntimeout = "долго"\n', "agent.timeout: Input should be a valid number"),
            ("[telegram]\ntoken = 1\n", "telegram: Extra inputs are not permitted"),
            ("[agent\n", "local.toml: "),
        ],
    )
    def test_mistake_in_a_file_names_the_file_and_the_field(self, tmp_path: Path, text: str, problem: str) -> None:
        local = write(tmp_path / "local.toml", text)

        with pytest.raises(SettingsError) as error:
            SettingsLoader(MODULE, "Live", [local]).load()

        assert str(local) in str(error.value) and problem in str(error.value)


class TestToolTimeout:
    def test_tool_must_end_before_the_phrase_does(self, tmp_path: Path) -> None:
        """Иначе ручка продолжала бы действовать после того, как пользователю уже ответили «не получилось»."""
        local = write(tmp_path / "local.toml", "tool_timeout = 120\n")

        with pytest.raises(SettingsError, match=r"tool_timeout \(120\) must be positive and less than agent.timeout \(90\)"):
            SettingsLoader(MODULE, "Live", [local]).load()

    def test_default_tool_timeout_fits_the_default_phrase(self) -> None:
        settings = SettingsLoader(MODULE, "Live").load()

        assert 0 < settings.tool_timeout < settings.agent.timeout


class TestSettingsTypes:
    def test_command_is_written_as_a_line_and_read_as_arguments(self) -> None:
        settings = NotesSettings.model_validate({"editor": "~/.local/bin/zed --new"})

        assert settings.editor == (str(Path.home() / ".local/bin/zed"), "--new")

    def test_empty_command_line_means_no_command(self) -> None:
        """`host = ""` в файле машины — «не задано», а не ошибка разбора (проба серверного ассистента без входа на хост)."""
        assert NotesSettings.model_validate({"editor": ""}).editor == ()
        assert NotesSettings.model_validate({"editor": "   "}).editor == ()

    def test_sections_are_immutable(self) -> None:
        with pytest.raises(Exception, match="frozen"):
            NotesSettings().folder = Path("/tmp")   # type: ignore[misc]


class TestSkillSection:
    def test_skill_without_a_section_in_the_project_gets_its_defaults(self) -> None:
        class CalendarSettings(SkillSettings):
            days_ahead: int = 7

        assert SettingsLoader(MODULE, "Live").load().skill("calendar", CalendarSettings).days_ahead == 7
