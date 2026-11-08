from pathlib import Path

import pytest
from pydantic import Field

from jericho.backends.scripted.client import ScriptedBackend
from jericho.backends.scripted.script import read_script
from jericho.core import Risk, Tool, ToolDescription, ToolRefusal, ToolRequest, ToolResult
from jericho.core.agent.entities import AgentReply, ReplyStatus
from jericho.core.agent.forms import Brief, Report
from jericho.core.agent.handle_phrase import HandlePhrase
from jericho.core.backends.config import BackendError
from jericho.core.testing import builder
from jericho.core.tools.dispatcher import ToolDispatcher
from jericho.core.tools.middleware import Journal, Refusals

SCRIPT = """
- when: открой
  calls:
    - tool: open
      arguments: {what: ютуб}
    - tool: open
      arguments: {what: ""}
    - tool: shell
  reply: {status: done, message: Открыл ютуб}
- reply: {status: ignored, message: ""}
"""


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


def backend(tmp_path: Path, text: str = SCRIPT, form: Brief | Report | None = None) -> tuple[ScriptedBackend, Open]:
    file = tmp_path / "script.yaml"
    file.write_text(text, encoding="utf-8")
    tool = Open()
    schema = (form or Brief()).schema()
    return ScriptedBackend(read_script(file), [tool], ToolDispatcher([Journal, Refusals]), schema), tool


class TestScriptedBackend:
    def test_calls_the_real_tools_through_the_dispatcher_and_answers_by_the_script(self, tmp_path: Path) -> None:
        scripted, tool = backend(tmp_path)

        answer = scripted.ask("ПРОМПТ", "Открой ютуб")

        assert (answer.structured, tool.opened) == ({"status": "done", "message": "Открыл ютуб"}, ["ютуб"])
        assert answer.meta["calls"] == [{"tool": "open", "ok": True}, {"tool": "open", "error": "empty"}, {"tool": "shell", "error": "unknown_tool"}]

    def test_record_without_words_answers_everything_else(self, tmp_path: Path) -> None:
        assert backend(tmp_path)[0].ask("ПРОМПТ", "так, короче").structured == {"status": "ignored", "message": ""}

    def test_whole_scenario_runs_without_a_model(self, tmp_path: Path) -> None:
        scripted, tool = backend(tmp_path)

        assert HandlePhrase(builder(), scripted).execute("открой ютуб") == AgentReply(ReplyStatus.DONE, "Открыл ютуб")
        assert tool.opened == ["ютуб"]

    @pytest.mark.parametrize(("form", "fields"), [(Brief(), {"message"}), (Report(), {"title", "text"})])
    def test_without_a_record_it_refuses_in_the_form_the_project_chose(self, tmp_path: Path, form: Brief | Report, fields: set[str]) -> None:
        scripted, _ = backend(tmp_path, "[]", form)

        answer = scripted.ask("ПРОМПТ", "открой ютуб").structured

        assert answer is not None and set(answer) == {"status", *fields}
        assert form.parse(answer).status is ReplyStatus.REFUSED and "сценарии нет записи" in form.parse(answer).message

    @pytest.mark.parametrize(("text", "problem"), [
        ("- when: открой", "record 1: needs `reply`"),
        ("- reply: {status: done}\n  calls: open", "record 1: `calls` must be a list"),
        ("status: done", "must be a list of records"),
        ("- [", "script.yaml: "),
    ])
    def test_wrong_script_says_which_record_is_wrong(self, tmp_path: Path, text: str, problem: str) -> None:
        with pytest.raises(BackendError, match=problem):
            backend(tmp_path, text)
