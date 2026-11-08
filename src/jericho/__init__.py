"""Jericho — каркас для ассистентов: модель получает набор действий, каждое проходит проверки в коде и остаётся в журнале."""

import os
import sys
from pathlib import Path


def main() -> None:
    """Собирает ассистента, названного в `JERICHO_SETTINGS_MODULE`, и запускает его команду.

    Проект называет себя сам — своей точкой входа, как `manage.py` у проекта на Django. Без проекта
    у каркаса одна команда — `startproject`, как у `django-admin`.
    """
    from jericho.core.assembly.installation import Installation, InstallationError
    from jericho.core.backends.config import BackendError
    from jericho.core.conf.loader import SettingsError
    from jericho.core.conf.resources import ResourceError
    from jericho.core.interfaces.cli import run
    from jericho.core.modules.registry import ModuleError
    from jericho.core.shared.registry import ServiceError
    from jericho.core.skills.loader import SkillLoadError
    from jericho.core.tools.loader import MiddlewareLoadError

    if not os.environ.get(Installation.SETTINGS_VARIABLE):
        run(_framework_commands())
        return
    from jericho.bootstrap import build_commands

    errors = (
        InstallationError, SettingsError, SkillLoadError, MiddlewareLoadError, ResourceError, ModuleError,
        BackendError, ServiceError,
    )  # fmt: skip
    try:
        commands = build_commands()
    except errors as error:   # ошибка в настройках — без трассировки
        sys.exit(f"jericho: settings: {error}")
    run(commands)


def _framework_commands() -> list:
    """Команды каркаса без проекта. Остальные команды — у проекта: `<проект> ask`, `<проект> check`."""
    from jericho.core.interfaces.cli.start_commands import StartProjectCommand
    from jericho.core.management.scaffold import ProjectScaffold

    repository = Path(__file__).resolve().parents[2]      # каркас стоит из исходников, если рядом его pyproject.toml
    source = repository if (repository / "pyproject.toml").exists() else None
    return [StartProjectCommand(ProjectScaffold(source), Path.cwd())]
