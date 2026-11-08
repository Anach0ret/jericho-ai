"""Команда терминала, которой программа модели (claude, codex) поднимает сервер ручек."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from typing import Any

from jericho.core.tools.dispatcher import ToolDispatcher
from jericho.core.tools.tool import Tool


class McpCommand:
    name = "mcp"
    help = "MCP-сервер с инструментами; его запускает программа модели (claude, codex), вручную не нужен"

    def __init__(self, tools: Sequence[Tool[Any]], dispatcher: ToolDispatcher) -> None:
        self._tools = tuple(tools)
        self._dispatcher = dispatcher

    def configure(self, parser: argparse.ArgumentParser) -> None:
        pass

    def run(self, args: argparse.Namespace) -> None:
        from jericho.backends.mcp_tools.server import JerichoMcpServer  # библиотека mcp нужна только самому серверу

        JerichoMcpServer(self._tools, self._dispatcher).run()
