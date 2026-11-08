"""Прогон проверочных фраз не трогает рабочие файлы (ревью R01)."""

import sys
from pathlib import Path

import pytest

from jericho.core.assembly.installation import Installation
from jericho.core.assembly.modules import load_modules, ready_modules
from jericho.core.assembly.skills import build_skills
from jericho.core.assembly.state import build_state
from jericho.core.evals.adapters.process_runner import ProcessPhraseRunner
from jericho.core.journal.adapters.jsonl import JsonLinesLogReader
from jericho.core.modules.registry import InstalledModules
from jericho.core.services.paths import Paths


def working_assistant(tmp_path: Path) -> tuple[InstalledModules, Paths]:
    """Обычный запуск (не Eval) с модулями, у которых есть свои файлы: заметки и разговор."""
    environment = {
        Installation.SETTINGS_VARIABLE: "tests.core.sample_settings",
        Installation.CONFIGURATION_VARIABLE: "WithMemory",
        "XDG_STATE_HOME": str(tmp_path / "state"),
        "XDG_RUNTIME_DIR": str(tmp_path / "run"),
    }
    installation = Installation.discover(environment, tmp_path, sys.executable)
    settings = installation.settings()
    state = build_state(settings, installation)
    modules = load_modules(settings)
    skills = build_skills(settings, state, modules)
    ready_modules(modules, settings, state, skills.installed, installation)     # модули захватили рабочие пути
    return modules, state.files.paths


class TestEvalIsolation:
    def test_files_to_forget_are_the_eval_ones_and_working_files_survive(self, tmp_path: Path) -> None:
        modules, working = working_assistant(tmp_path)
        notes, conversation = working.state_dir / "notes.json", working.runtime_dir / "conversation.json"
        notes.write_text("{}", encoding="utf-8")
        conversation.write_text("[]", encoding="utf-8")
        eval_paths = Paths(tmp_path / "state" / "eval", tmp_path / "run" / "eval")

        files = modules.eval_files(eval_paths)
        runner = ProcessPhraseRunner(
            ["true"], {}, JsonLinesLogReader(tmp_path / "j.jsonl"), files, roots=(eval_paths.state_dir, eval_paths.runtime_dir)
        )
        runner.forget()

        assert files and all(file.is_relative_to(tmp_path / "state" / "eval") or file.is_relative_to(tmp_path / "run" / "eval") for file in files)
        assert notes.exists() and conversation.exists()

    def test_eval_refuses_to_remove_anything_outside_its_folders(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="outside its own folders"):
            ProcessPhraseRunner(["true"], {}, JsonLinesLogReader(tmp_path / "j.jsonl"), [tmp_path / "notes.json"], roots=(tmp_path / "eval",))
