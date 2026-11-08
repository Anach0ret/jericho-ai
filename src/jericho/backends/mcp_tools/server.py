"""MCP-сервер Jericho: отдаёт ручки модели.

Сервер запускает программа модели (`claude`, `codex`) на время одного запроса. Он ничего не знает о конкретных ручках:
имя, описание и схема параметров объявлены в классе ручки (`skills/<навык>/tools/`), сервер только переводит
их в формат протокола. У ручек навыков в списке — одна строка: полное описание модель получает вместе
с руководством навыка, по `load_skill`. Новая ручка появляется у модели без правок в этом файле.

Параметры сервер не проверяет: вызов уходит в диспетчер как есть, и неверные параметры возвращаются модели
обычным отказом `invalid_parameters` — через те же слои и с записью в журнал.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from typing import Any

from mcp import types
from mcp.server.lowlevel.server import Server
from mcp.server.stdio import stdio_server

from jericho.core.skills.load_skill import brief_description
from jericho.core.tools.dispatcher import ToolDispatcher
from jericho.core.tools.result import ToolResult
from jericho.core.tools.tool import Tool


class JerichoMcpServer:
    """Собирает сервер из ручек и запускает его на стандартном вводе-выводе."""

    NAME = "jericho"
    UNKNOWN_TOOL = "unknown_tool"

    def __init__(self, tools: Sequence[Tool[Any]], dispatcher: ToolDispatcher) -> None:
        self._tools = {tool.name: tool for tool in tools}
        self._dispatcher = dispatcher

    def offered(self) -> list[types.Tool]:
        """Ручки в том виде, в каком их получает модель."""
        return [
            types.Tool(
                name=tool.name,
                description=brief_description(tool),
                input_schema=tool.request_type.tool_schema(),
                annotations=types.ToolAnnotations(destructive_hint=tool.destructive, read_only_hint=tool.read_only),
            )
            for tool in self._tools.values()
        ]

    def call(self, name: str, arguments: dict[str, Any] | None) -> dict[str, object]:
        """Вызов ручки по имени; ответ — словарь, который увидит модель."""
        return self._result(name, arguments).to_dict()

    def reply(self, name: str, arguments: dict[str, Any] | None) -> types.CallToolResult:
        """Ответ на вызов в формате протокола. Отказ ручки — ошибка выполнения: её видит модель и может поправиться.

        Картинки ручки (кадры видео, фото) идут следом за текстом: программа claude показывает их модели.
        """
        result = self._result(name, arguments)
        answer = result.to_dict()
        text = json.dumps(answer, ensure_ascii=False)
        images = [types.ImageContent(type="image", data=image.base64, mime_type=image.media_type) for image in result.images]
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=text), *images],
            structured_content=answer,
            is_error=answer["ok"] is not True,
        )

    def _result(self, name: str, arguments: dict[str, Any] | None) -> ToolResult:
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult.failure(self.UNKNOWN_TOOL, available=list(self._tools))
        return self._dispatcher.call(tool, arguments or {})

    def build(self) -> Server[Any]:
        return Server(self.NAME, on_list_tools=self._on_list_tools, on_call_tool=self._on_call_tool)

    def run(self) -> None:
        asyncio.run(self._serve())

    async def _serve(self) -> None:
        server = self.build()
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())

    async def _on_list_tools(self, context: Any, params: types.PaginatedRequestParams | None) -> types.ListToolsResult:
        return types.ListToolsResult(tools=self.offered())

    async def _on_call_tool(self, context: Any, params: types.CallToolRequestParams) -> types.CallToolResult:
        # Ручка работает синхронно и недолго (срок — tool_timeout); сервер живёт один запрос и обслуживает одного клиента.
        return self.reply(params.name, params.arguments)
