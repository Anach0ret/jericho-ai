"""Composition root каркаса: порядок сборки приложения из проекта, названного в окружении.

Саму сборку ведут участки ядра (`core/assembly/`): состояние → модули и навыки → ручки → агент → команды.
Навыки собирают себя сами, каждый в своём `skill.py`. Какой проект собирается, решает переменная
`JERICHO_SETTINGS_MODULE`; что в нём подключено и с какими значениями — его настройки и файлы этой машины
(`~/.config/<имя проекта>/`). Ни одного имени проекта в этом файле нет.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from jericho.core.assembly.agent import build_agent
from jericho.core.assembly.commands import build_commands as build_core_commands
from jericho.core.assembly.installation import Installation
from jericho.core.assembly.modules import load_modules, ready_modules
from jericho.core.assembly.skills import build_skills
from jericho.core.assembly.state import build_state
from jericho.core.assembly.tools import build_toolset
from jericho.core.management.base import Command


def build_commands(installation: Installation | None = None) -> tuple[Command, ...]:
    """Всё приложение в виде команд терминала: поручение, сервер ручек, проверки — каждая из них команда."""
    installation = installation or Installation.discover(os.environ, Path.home(), sys.executable)
    settings = installation.settings()
    state = build_state(settings, installation)
    modules = load_modules(settings)
    skills = build_skills(settings, state, modules)
    ready_modules(modules, settings, state, skills.installed, installation)
    toolset = build_toolset(settings, skills, modules, state)
    agent = build_agent(settings, skills, modules, toolset, state, installation)
    return build_core_commands(settings, installation, state, skills, modules, toolset, agent)
