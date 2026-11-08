import asyncio
import time

from mcp import types
from pydantic import Field

from jericho.backends.mcp_tools.server import JerichoMcpServer
from jericho.backends.tool_loop.testing import FRAME, Look
from jericho.core import Risk, Tool, ToolDescription, ToolRefusal, ToolRequest, ToolResult
from jericho.core.tools.deadline import Deadline
from jericho.core.tools.dispatcher import ToolDispatcher
from jericho.core.tools.middleware import Journal, Refusals

DISPATCHER = ToolDispatcher([Journal, Refusals])


class EchoRequest(ToolRequest):
    text: str = Field(description="Что повторить.")


class Echo(Tool[EchoRequest]):
    name = "echo"
    risk = Risk.READ
    description = ToolDescription(when="Просят повторить.", does="Повторяет.", returns="Текст.", refusals="empty.")
    request_type = EchoRequest

    def _run(self, request: EchoRequest) -> ToolResult:
        if not request.text:
            raise ToolRefusal("empty")
        return ToolResult.success(said=request.text)


class Erase(Echo):
    name = "erase"
    risk = Risk.EFFECT


def server() -> JerichoMcpServer:
    return JerichoMcpServer([Echo(), Erase()], DISPATCHER)


class TestJerichoMcpServer:
    def test_offers_every_tool_under_its_own_name_with_a_schema_from_the_request(self) -> None:
        offered = server().offered()

        assert [tool.name for tool in offered] == ["echo", "erase"]
        assert offered[0].input_schema["properties"]["text"]["description"] == "Что повторить."

    def test_risk_reaches_the_model_as_hints(self) -> None:
        hints = {
            tool.name: (tool.annotations.read_only_hint, tool.annotations.destructive_hint)
            for tool in server().offered()
            if tool.annotations
        }

        assert hints == {"echo": (True, False), "erase": (False, True)}

    def test_call_goes_through_the_dispatcher_and_comes_back_as_a_dictionary(self) -> None:
        assert server().call("echo", {"text": "привет"}) == {"ok": True, "said": "привет"}

    def test_refusal_and_unknown_tool_are_tool_errors_of_the_protocol(self) -> None:
        calls = (("echo", {"text": "да"}), ("echo", {"text": ""}), ("shell", {}))
        done, refused, unknown = (server().reply(name, arguments) for name, arguments in calls)

        assert (done.is_error, refused.is_error, unknown.is_error) == (False, True, True)
        assert unknown.structured_content == {"ok": False, "error": "unknown_tool", "available": ["echo", "erase"]}

    def test_tool_images_follow_the_text(self) -> None:
        reply = JerichoMcpServer([Look()], DISPATCHER).reply("look", {"what": "видео"})

        text, image = reply.content
        assert isinstance(text, types.TextContent) and isinstance(image, types.ImageContent)
        assert (image.data, image.mime_type) == (FRAME.base64, "image/jpeg")
        assert reply.structured_content == {"ok": True, "frames": 1}

    def test_slow_tool_is_cut_off_inside_the_running_server(self) -> None:
        """Срок ручки держится и там, где он нужен: в цикле событий сервера, который поднимает claude."""
        class WaitRequest(ToolRequest):
            pass

        class Wait(Tool[WaitRequest]):
            name = "wait"
            description = ToolDescription(when="Никогда.", does="Ждёт.", returns="Ничего.", refusals="нет.")
            request_type = WaitRequest

            def _run(self, request: WaitRequest) -> ToolResult:
                until = time.monotonic() + 5      # работа на Python: её срок обрывает на любой ОС
                while time.monotonic() < until:
                    pass
                return ToolResult.success()

        server = JerichoMcpServer([Wait()], ToolDispatcher([Journal, Refusals], deadline=Deadline(0.1)))
        started = time.perf_counter()

        answer = asyncio.run(server._on_call_tool(None, types.CallToolRequestParams(name="wait", arguments={})))  # pyright: ignore[reportPrivateUsage]

        assert answer.is_error and answer.structured_content is not None
        assert answer.structured_content["error"] == "tool_timeout"
        assert time.perf_counter() - started < 2
