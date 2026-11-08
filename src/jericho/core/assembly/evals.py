"""Участок «проверочные фразы»: прогон идёт отдельными процессами в своём варианте настроек."""

from __future__ import annotations

from jericho.core.assembly.installation import Installation
from jericho.core.assembly.state import StateFiles
from jericho.core.assembly.tools import Toolset
from jericho.core.conf.loader import SettingsError
from jericho.core.evals.adapters.json_runs import JsonRunStore
from jericho.core.evals.adapters.markdown_file import MarkdownEvalFile
from jericho.core.evals.adapters.process_runner import ProcessPhraseRunner
from jericho.core.evals.session import EvalSession
from jericho.core.interfaces.cli.eval_command import EvalCommand
from jericho.core.journal.adapters.jsonl import JsonLinesLogReader
from jericho.core.modules.registry import InstalledModules
from jericho.core.skills.registry import InstalledSkills


def build_eval_command(
    installation: Installation, skills: InstalledSkills, modules: InstalledModules, toolset: Toolset
) -> EvalCommand:
    """Команда запускает фразы в варианте Eval и читает журнал этого варианта — не рабочий."""
    configuration = installation.EVAL_CONFIGURATION
    settings = installation.settings(configuration)
    if not settings.dry_run:      # прогон гоняет настоящую модель по настоящим ручкам: только вхолостую
        raise SettingsError(f"{configuration}: the eval configuration must have dry_run = True")
    files = StateFiles(settings, installation)
    skill_files = ((skill.name, skill.directory / installation.EVALS_FILE) for skill in skills)
    sources = [
        MarkdownEvalFile("core", installation.core_evals),
        *(MarkdownEvalFile(name, file) for name, file in skill_files if file.exists()),
    ]
    runner = ProcessPhraseRunner(
        command=(*installation.launch, "ask"),
        environment={**installation.environment, **installation.environment_for(configuration)},
        journal=JsonLinesLogReader(files.journal),
        conversation_files=(files.confirmation, *modules.eval_files(files.paths)),   # каждая фраза — с чистого листа
        roots=(files.paths.state_dir, files.paths.runtime_dir),       # стирать можно только внутри папок прогона
    )
    connected = tuple(name for name in toolset.names if name not in toolset.service)
    session = EvalSession(sources, runner, connected_tools=connected, service_tools=toolset.service)
    return EvalCommand(session, JsonRunStore(files.eval_runs))
