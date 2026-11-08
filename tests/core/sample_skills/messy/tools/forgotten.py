from jericho.core import ToolResult
from tests.core.sample_skills.messy.tools.listed import Listed, ListedRequest


class Forgotten(Listed):
    name = "forgotten"

    def _run(self, request: ListedRequest) -> ToolResult:
        return ToolResult.success()
