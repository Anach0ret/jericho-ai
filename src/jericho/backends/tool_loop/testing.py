"""Подмены для тестов бэкендов по ключу: простая ручка и готовый ответ."""

from pydantic import Field

from jericho.core import Approval, Risk, Tool, ToolDescription, ToolImage, ToolRefusal, ToolRequest, ToolResult

DONE: dict[str, object] = {"status": "done", "message": "Открыл"}
FRAME = ToolImage(b"\xff\xd8jpeg", "image/jpeg")


class OpenRequest(ToolRequest):
    what: str = Field(description="Что открыть.")


class Open(Tool[OpenRequest]):
    name = "open"
    risk = Risk.NAVIGATE
    description = ToolDescription(when="Просят открыть.", does="Открывает.", returns="Что открыто.", refusals="empty.")
    request_type = OpenRequest

    def __init__(self) -> None:
        self.opened: list[str] = []

    def _run(self, request: OpenRequest) -> ToolResult:
        if not request.what:
            raise ToolRefusal("empty")
        self.opened.append(request.what)
        return ToolResult.success(opened=request.what)


class Send(Open):
    """Действие с последствиями, о согласии на которое заботится каркас."""

    name = "send"
    risk = Risk.EFFECT
    approval = Approval.ASK


class Look(Open):
    """Ручка, которая показывает модели картинку — как кадр видео."""

    name = "look"
    risk = Risk.READ

    def _run(self, request: OpenRequest) -> ToolResult:
        return ToolResult.success(frames=1).showing([FRAME])
