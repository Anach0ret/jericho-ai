from jericho.core import Tool, ToolDescription, ToolRequest, ToolResult


class ListedRequest(ToolRequest):
    text: str


class Listed(Tool[ListedRequest]):
    name = "listed"
    description = ToolDescription(when="Всегда.", does="Ничего.", returns="Ничего.", refusals="Нет.")
    request_type = ListedRequest

    def _run(self, request: ListedRequest) -> ToolResult:
        return ToolResult.success()
