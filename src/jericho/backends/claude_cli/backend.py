"""Бэкенд «программа claude»: модель по подписке, цикл вызовов ведёт сама программа через наш сервер ручек."""

from __future__ import annotations

from collections.abc import Sequence

from jericho.backends.claude_cli.client import ClaudeCliBackend
from jericho.backends.claude_cli.settings import ClaudeSettings
from jericho.backends.mcp_tools.command import McpCommand
from jericho.core.agent.active_backend import ActiveBackend
from jericho.core.agent.protocols import AgentBackend
from jericho.core.backends.config import BackendConfig, BackendServices
from jericho.core.management.base import Command
from jericho.core.services.runner import SubprocessRunner


class ClaudeCli(BackendConfig):
    name = "claude_cli"
    settings_class = ClaudeSettings

    # Встроенные инструменты, которые приносят модели чужой текст мимо наших ручек. Что именно модель нашла,
    # каркас не видит, поэтому фраза, где они разрешены, целиком считается прочитавшей чужое (ревью R06).
    READS_THE_WEB = frozenset({"WebSearch", "WebFetch"})

    def ready(self, services: BackendServices) -> None:
        self._claude = services.settings.section(self.name, ClaudeSettings)
        self._services = services
        if self.READS_THE_WEB & set(self._claude.builtin_tools):
            services.foreign.read_from("web_search")

    def backend(self) -> AgentBackend:
        services = self._services
        return ClaudeCliBackend(
            runner=SubprocessRunner(timeout=services.settings.agent.timeout, deadline=services.deadline),
            executable=self._claude.claude,
            model=self._claude.model,
            mcp_command=(*services.launch, McpCommand.name),
            tools=[tool.name for tool in services.tools],
            reply_schema=services.reply_schema,
            # Сервер ручек — отдельный процесс: кто ведёт фразу, он узнаёт отсюда (политика личных данных).
            mcp_environment={**services.child_environment, ActiveBackend.VARIABLE: self.name},
            deadline=services.deadline,      # срок фразы — серверу ручек при каждом запуске модели
            builtin_tools=self._claude.builtin_tools,
        )

    def commands(self) -> Sequence[Command]:
        return (McpCommand(self._services.tools, self._services.dispatcher),)
