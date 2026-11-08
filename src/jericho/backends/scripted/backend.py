"""Бэкенд «сценарий»: ассистент без модели — для тестов, пробных запусков и первых шагов нового проекта."""

from __future__ import annotations

from jericho.backends.scripted.client import ScriptedBackend
from jericho.backends.scripted.script import read_script
from jericho.backends.scripted.settings import ScriptedSettings
from jericho.core.agent.protocols import AgentBackend
from jericho.core.backends.config import BackendConfig, BackendError, BackendServices
from jericho.core.conf.resources import ResourceError, package_file


class Scripted(BackendConfig):
    """То же, что SQLite у Django: работает сразу после установки, ничего не требуя."""

    name = "scripted"
    settings_class = ScriptedSettings

    def ready(self, services: BackendServices) -> None:
        self._services = services
        script = services.settings.section(self.name, ScriptedSettings).script
        try:
            self._steps = read_script(package_file(script, "scripted.script")) if script else ()
        except ResourceError as error:
            raise BackendError(str(error)) from error

    def backend(self) -> AgentBackend:
        services = self._services
        return ScriptedBackend(self._steps, services.tools, services.dispatcher, services.reply_schema)
