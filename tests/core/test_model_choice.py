import argparse
from pathlib import Path

import pytest

from jericho.backends.claude_cli.settings import ClaudeSettings
from jericho.backends.openai_api.settings import OpenAiSettings
from jericho.core.agent.model_choice import ModelChoiceFile, ModelChoices
from jericho.core.assembly.agent import model_choices
from jericho.core.conf.settings import AgentSettings, ModelChoice, Settings
from jericho.core.interfaces.cli.model_command import ModelCommand

CLAUDE, OPENAI = "jericho.backends.claude_cli", "jericho.backends.openai_api"
NAMES = {CLAUDE: "claude_cli", OPENAI: "openai_api"}


class Project(Settings):
    claude_cli: ClaudeSettings = ClaudeSettings(model="haiku")
    openai_api: OpenAiSettings = OpenAiSettings(base_url="https://example.invalid/v1/", model="gemini-flash")
    agent: AgentSettings = AgentSettings(backend=CLAUDE, fallback_backends=(OPENAI,), models={
        "haiku": ModelChoice(label="Haiku", backend=CLAUDE, model="haiku"),
        "opus": ModelChoice(label="Opus", backend=CLAUDE, model="opus"),
        "gemini": ModelChoice(label="Gemini", backend=OPENAI),
    })


def choices() -> ModelChoices:
    return ModelChoices(Project(), NAMES.__getitem__)


class TestModelChoices:
    def test_backend_without_its_section_takes_its_defaults(self) -> None:
        """Раздел бэкенда необязателен — а выбор модели требовал его и ломал сборку (ревью 02.11.2026, П2 №10)."""

        class Bare(Settings):
            agent: AgentSettings = AgentSettings(backend=CLAUDE, models={"opus": ModelChoice(label="Opus", backend=CLAUDE, model="opus")})

        settings = model_choices(Bare()).applied("opus")

        assert settings.section("claude_cli", ClaudeSettings).model == "opus"

    def test_a_model_for_a_backend_without_settings_is_a_clear_error(self) -> None:
        bare = ModelChoices(Settings(agent=AgentSettings(backend=CLAUDE, models={"x": ModelChoice(label="X", backend=CLAUDE, model="x")})), str)

        with pytest.raises(ValueError, match="remove `model`"):
            bare.applied("x")

    def test_default_is_the_choice_matching_the_settings(self) -> None:
        assert choices().default() == "haiku"

    def test_chosen_model_replaces_the_main_one_and_keeps_the_chain(self) -> None:
        settings = choices().applied("opus")

        assert (settings.agent.backend, settings.agent.fallback_backends) == (CLAUDE, (OPENAI,))
        assert settings.section("claude_cli", ClaudeSettings).model == "opus"

    def test_another_backend_becomes_main_and_the_old_one_spare(self) -> None:
        settings = choices().applied("gemini")

        assert (settings.agent.backend, settings.agent.fallback_backends) == (OPENAI, (CLAUDE,))
        assert settings.section("openai_api", OpenAiSettings).model == "gemini-flash"     # пустая model — как в разделе

    def test_nothing_chosen_or_unknown_name_keeps_the_settings(self) -> None:
        project = choices()

        assert project.applied(None) is project.settings
        assert project.applied("gpt") is project.settings       # пункт убрали из настроек — по умолчанию

    def test_choice_must_use_a_configured_backend(self) -> None:
        with pytest.raises(ValueError, match="agent.models.other"):
            AgentSettings(backend=CLAUDE, models={"other": ModelChoice(label="?", backend="jericho.backends.anthropic_api")})


class TestModelCommand:
    def run(self, tmp_path: Path, *argv: str) -> tuple[ModelCommand, ModelChoiceFile]:
        chosen = ModelChoiceFile(tmp_path / "model.json")
        command = ModelCommand(choices(), chosen)
        parser = argparse.ArgumentParser()
        command.configure(parser)
        command.run(parser.parse_args(list(argv)))
        return command, chosen

    def test_choice_holds_until_reset(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        command, chosen = self.run(tmp_path, "opus")

        assert chosen.current() == "opus" and command.current() == "opus"
        assert "* opus" in capsys.readouterr().out

        command, chosen = self.run(tmp_path, "--reset")
        assert chosen.current() is None and command.current() == "haiku"

    def test_unknown_name_is_refused_by_the_parser(self, tmp_path: Path) -> None:
        with pytest.raises(SystemExit):
            self.run(tmp_path, "gpt")
