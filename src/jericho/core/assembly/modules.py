"""Участок «модули ядра»: подключить названные в настройках и выдать им службы каркаса."""

from __future__ import annotations

from jericho.core.assembly.installation import Installation
from jericho.core.assembly.state import State
from jericho.core.conf.settings import Settings
from jericho.core.modules.config import ModuleServices
from jericho.core.modules.loader import ModuleLoader
from jericho.core.modules.registry import InstalledModules
from jericho.core.services.program import Program
from jericho.core.services.relaunch import ProcessRelaunch
from jericho.core.skills.registry import InstalledSkills


def load_modules(settings: Settings) -> InstalledModules:
    """Модули находятся раньше навыков: руководство навыка должно знать, кто его дополняет."""
    return ModuleLoader().load(settings.INSTALLED_MODULES)


def ready_modules(
    modules: InstalledModules, settings: Settings, state: State, skills: InstalledSkills, installation: Installation
) -> None:
    """Собираются модули после навыков: им нужны имена навыков и их ручки."""
    relaunch = ProcessRelaunch(installation.launch, installation.unattended_environment(), installation.attended)
    program = Program(
        name=installation.program,
        command=installation.launch,
        environment=installation.environment_for(installation.configuration),
        config_dir=installation.config_dir,
        user_config_home=installation.user_config_home,
    )
    modules.ready(ModuleServices(settings, state.services, state.journal, state.session, skills, state.tools, relaunch, program, state.run_id))
