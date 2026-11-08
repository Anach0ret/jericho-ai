"""Бэкенд «программа codex»: модель по подписке ChatGPT, цикл вызовов ведёт сама программа через наш сервер ручек."""

from __future__ import annotations

from collections.abc import Sequence

from jericho.backends.codex_cli.client import CodexCliBackend
from jericho.backends.codex_cli.settings import CodexSettings
from jericho.backends.mcp_tools.command import McpCommand
from jericho.core.agent.active_backend import ActiveBackend
from jericho.core.agent.protocols import AgentBackend
from jericho.core.backends.config import BackendConfig, BackendServices
from jericho.core.management.base import Command
from jericho.core.services.runner import SubprocessRunner


class CodexCli(BackendConfig):
    name = "codex_cli"
    settings_class = CodexSettings
    TOOL_TIMEOUT_MARGIN = 5.0

    def ready(self, services: BackendServices) -> None:
        self._codex = services.settings.section(self.name, CodexSettings)
        self._services = services

    def backend(self) -> AgentBackend:
        services = self._services
        return CodexCliBackend(
            runner=SubprocessRunner(timeout=services.settings.agent.timeout, deadline=services.deadline),
            executable=self._codex.codex,
            model=self._codex.model,
            reasoning_effort=self._codex.reasoning_effort,
            mcp_command=(*services.launch, McpCommand.name),
            tools=[tool.name for tool in services.tools],
            reply_schema=services.reply_schema,
            # Сервер ручек — отдельный процесс: кто ведёт фразу, он узнаёт отсюда (политика личных данных).
            mcp_environment={**services.child_environment, ActiveBackend.VARIABLE: self.name},
            deadline=services.deadline,      # срок фразы — серверу ручек при каждом запуске модели
            disabled_features=self._codex.disabled_features,
            # Срок вызова у codex — чуть больше своего срока ручки (`tool_timeout`): срок держит каркас, а не codex.
            tool_timeout=services.settings.tool_timeout + self.TOOL_TIMEOUT_MARGIN,
        )

    def commands(self) -> Sequence[Command]:
        return (McpCommand(self._services.tools, self._services.dispatcher),)
