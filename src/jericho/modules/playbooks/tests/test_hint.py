"""Подсказка памятки из кода: открыли сайт, у которого есть памятка, — ответ ручки о ней напоминает."""

from datetime import datetime

from pydantic import Field

from jericho.core import Risk, Tool, ToolCall, ToolDescription, ToolRequest, ToolResult
from jericho.core.services.adapters.memory_list import MemoryList
from jericho.core.tools.session import CallSession
from jericho.modules.playbooks.entities import Playbook
from jericho.modules.playbooks.hint import PlaybookHint
from jericho.modules.playbooks.shelf import PlaybookShelf

NOON = datetime(2026, 10, 31, 12, 0)


class OpenRequest(ToolRequest):
    url: str = Field(default="")


class Open(Tool[OpenRequest]):
    name = "page_open"
    risk = Risk.NAVIGATE
    request_type = OpenRequest
    description = ToolDescription(when="—", does="—", returns="—", refusals="—")

    def _run(self, request: OpenRequest) -> ToolResult:
        return ToolResult.success()


def shelf(*playbooks: Playbook) -> PlaybookShelf:
    return PlaybookShelf(MemoryList[Playbook](playbooks), lambda: NOON)


QUIZ = Playbook("f2e3d2", "Пройти тест в Moodle", "example.org", "1. «Пройти тест» …", NOON)


def call(hint: PlaybookHint, url: str = "", result: ToolResult | None = None, tool: Tool[OpenRequest] | None = None, **arguments: object) -> ToolResult:
    layer = hint(lambda _: result or ToolResult.success())
    return layer(ToolCall(tool or Open(), {"url": url, **arguments} if url else arguments, CallSession(())))


class TestHint:
    def test_opening_a_site_with_a_playbook_names_it_once(self) -> None:
        hint = PlaybookHint(shelf(QUIZ))

        first, again = call(hint, "https://lms.example.org/course/view.php?id=7"), call(hint, "https://lms.example.org/mod/quiz")

        assert first.data["playbook"] == {"id": "f2e3d2", "title": "Пройти тест в Moodle", "hint": "есть памятка для этого сайта — playbook_show до следующего действия"}
        assert "playbook" not in again.data

    def test_address_from_the_answer_counts_too(self) -> None:
        clicked = ToolResult.success(clicked="Тест", page={"title": "Курс", "url": "https://example.org/quiz"})

        assert "playbook" in call(PlaybookHint(shelf(QUIZ)), result=clicked).data

    def test_read_playbook_is_not_repeated(self) -> None:
        hint = PlaybookHint(shelf(QUIZ))

        class Show(Open):
            name = "playbook_show"

        call(hint, tool=Show(), playbook="f2e3d2")

        assert "playbook" not in call(hint, "https://example.org/").data

    def test_other_sites_failures_and_unaccepted_playbooks_are_quiet(self) -> None:
        proposed = Playbook("aaaaaa", "Входящие", "mail.example", "", NOON)
        hint = PlaybookHint(shelf(QUIZ, proposed))

        assert "playbook" not in call(hint, "https://notexample.org/").data
        assert "playbook" not in call(hint, "https://mail.example/").data
        assert not call(hint, "https://example.org/", result=ToolResult.failure("page_error")).ok
