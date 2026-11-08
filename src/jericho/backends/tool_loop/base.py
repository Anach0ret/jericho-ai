"""Основа бэкендов по ключу API: цикл «модель → ручка → модель» ведёт наш процесс, `ToolLoop`."""

from __future__ import annotations

import os
from abc import abstractmethod
from typing import ClassVar, cast

from jericho.backends.tool_loop.key import EnvironmentKey
from jericho.backends.tool_loop.loop import ToolLoop
from jericho.backends.tool_loop.protocols import ChatModel
from jericho.backends.tool_loop.settings import ApiModelSettings
from jericho.core.agent.protocols import AgentBackend
from jericho.core.backends.config import BackendConfig, BackendError, BackendServices
from jericho.core.conf.settings import SettingsSection


class ToolLoopBackend[SettingsT: ApiModelSettings](BackendConfig):
    """Наследник объявляет имя и раздел настроек и говорит, как из раздела и ключа получается модель."""

    settings_class: ClassVar[type[SettingsSection] | None] = ApiModelSettings     # наследник называет свой

    def ready(self, services: BackendServices) -> None:
        # Параметр типа в ClassVar недопустим: что раздел того самого класса, держит объявление наследника.
        settings = cast(SettingsT, services.settings.section(self.name, self.settings_class or ApiModelSettings))
        model = self.model(settings, EnvironmentKey(settings.api_key_env, os.environ, settings.api_key_file))
        try:
            self._loop = ToolLoop(
                model, services.tools, services.dispatcher, services.reply_schema,
                timeout=services.settings.agent.timeout, max_turns=settings.max_turns, check_reply=services.check_reply,
                phrase=services.deadline,
            )
        except ValueError as error:
            raise BackendError(str(error)) from error

    def backend(self) -> AgentBackend:
        return self._loop

    @abstractmethod
    def model(self, settings: SettingsT, key: EnvironmentKey) -> ChatModel: ...
