"""Участок «команды терминала»: ядра, навыков и по одной на каждую ручку."""

from __future__ import annotations

from jericho.core.agent.model_choice import ModelChoiceFile
from jericho.core.assembly.agent import Agent, model_choices, private_replies
from jericho.core.assembly.evals import build_eval_command
from jericho.core.assembly.installation import Installation
from jericho.core.assembly.skills import SkillSet
from jericho.core.assembly.state import State
from jericho.core.assembly.tools import Toolset
from jericho.core.checks.base import Project
from jericho.core.checks.structure import DEFAULT_CHECKS
from jericho.core.conf.settings import Settings
from jericho.core.interfaces.cli.agent_commands import AskCommand, PromptCommand, StopCommand
from jericho.core.interfaces.cli.check_command import CheckCommand
from jericho.core.interfaces.cli.journal_commands import LogCommand
from jericho.core.interfaces.cli.model_command import ModelCommand
from jericho.core.interfaces.cli.start_commands import StartServiceCommand, StartSkillCommand, StartToolCommand
from jericho.core.interfaces.cli.status_command import StatusCommand
from jericho.core.interfaces.cli.tool_commands import ToolCommand
from jericho.core.management.base import Command
from jericho.core.management.scaffold import Scaffold
from jericho.core.modules.registry import InstalledModules
from jericho.core.services.adapters.file_lock import FileLock
from jericho.core.services.output import output_for
from jericho.core.services.stop import PhraseStopper


def build_commands(
    settings: Settings,
    installation: Installation,
    state: State,
    skills: SkillSet,
    modules: InstalledModules,
    toolset: Toolset,
    agent: Agent,
) -> tuple[Command, ...]:
    installed = skills.installed
    program = installation.program
    scaffold = Scaffold(installation.project_dir, installation.project_package, program)
    manual = toolset.manual_dispatcher(installed.names)
    paths = state.files.paths
    project = Project(
        installation.project_dir, installed, installation.core_dir, modules, settings, skills.source.core(),
        private_dirs=(installation.config_dir, paths.state_dir, paths.runtime_dir),
    )
    output = output_for(settings.output, program)
    model = ModelCommand(model_choices(settings), ModelChoiceFile(state.files.model_choice))
    # Прогон проверочных фраз идёт в своём варианте настроек; проект, который его не объявил, команды не получает.
    evals = (build_eval_command(installation, installed, modules, toolset),) if installation.has_configuration(installation.EVAL_CONFIGURATION) else ()
    return (
        AskCommand(agent.handle_phrase, output),
        PromptCommand(agent.prompts, skills.guides, installed.names),
        StopCommand(PhraseStopper(FileLock(state.files.phrase_lock))),
        *installed.commands(),
        LogCommand(state.journal),
        StatusCommand(program, state.gate, state.journal, modules, model, toolset.service, private_replies(state)),
        model,
        *modules.commands(agent.handle_phrase),
        *evals,
        CheckCommand(project, (*DEFAULT_CHECKS, *installed.checks(), *modules.checks())),
        StartSkillCommand(scaffold, installation.skills_package, program),
        StartToolCommand(scaffold, program),
        StartServiceCommand(scaffold, f"{installation.project_package}.services", program),
        *backend_commands(agent),
        *(ToolCommand(tool, manual) for tool in installed.tools()),
    )


def backend_commands(agent: Agent) -> tuple[Command, ...]:
    """Команды бэкендов — по одной на имя: сервер ручек `mcp` приносят и `claude_cli`, и `codex_cli`, а это один и
    тот же сервер; основной и запасной бэкенд вместе дали бы две команды с одним именем."""
    unique: dict[str, Command] = {}
    for backend in agent.backends:
        for command in backend.commands():
            unique.setdefault(command.name, command)
    return tuple(unique.values())

