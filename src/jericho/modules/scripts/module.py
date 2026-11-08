"""Модуль ядра «сценарии»: быстрые цепочки шагов — кнопкой в окне, командой `run` или голосом через `run_script`."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

from jericho.core.checks.base import Check
from jericho.core.management.base import Command
from jericho.core.modules.config import ModuleConfig, ModuleServices
from jericho.core.tools.tool import Tool
from jericho.modules.scripts.checks import ScriptsAreValid
from jericho.modules.scripts.command import RunCommand
from jericho.modules.scripts.runner import ScriptRunner
from jericho.modules.scripts.settings import ScriptsSettings
from jericho.modules.scripts.tools import RunScript

if TYPE_CHECKING:
    from jericho.core.agent.handle_phrase import HandlePhrase


class ScriptsModule(ModuleConfig):
    name = "scripts"

    def ready(self, services: ModuleServices) -> None:
        self._scripts = dict(services.settings.section(self.name, ScriptsSettings).items)
        self._catalog = services.tools

    def tools(self) -> Sequence[Tool[Any]]:
        # Голосом — только сценарии без фраз: модель внутри вызова модели не запускают (см. RunScript).
        return (RunScript(self._scripts, ScriptRunner(self._catalog)),) if self._scripts else ()

    def commands(self, handle_phrase: HandlePhrase) -> Sequence[Command]:
        return (RunCommand(self._scripts, ScriptRunner(self._catalog, handle_phrase.execute)),) if self._scripts else ()

    def checks(self) -> Sequence[Check]:
        return (ScriptsAreValid(),)

    def status(self) -> Mapping[str, object]:
        """Сценарии для кнопок окна на панели."""
        if not self._scripts:
            return {}
        return {"scripts": [{"name": name, "title": script.title, "uses_model": script.uses_model} for name, script in self._scripts.items()]}
