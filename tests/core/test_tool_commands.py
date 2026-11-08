"""Ручка из терминала: аргументы строятся из полей запроса и значат то же, что у модели (ревью 02.11.2026, П1 №8)."""

import argparse
import json

import pytest
from pydantic import Field

from jericho.core import Risk, Tool, ToolDescription, ToolRequest, ToolResult
from jericho.core.interfaces.cli.tool_commands import ToolCommand
from jericho.core.tools.dispatcher import ToolDispatcher
from jericho.core.tools.middleware import Refusals
from jericho.modules.plans.tools import CreatePlanRequest


class ToggleRequest(ToolRequest):
    enabled: bool = Field(description="Включить.")
    targets: list[int] = Field(description="Куда.")
    loud: bool = Field(default=True, description="Громко.")
    tags: list[str] | None = Field(default=None, description="Метки.")
    extra: dict[str, int] | None = Field(default=None, description="Прочее.")


class Toggle(Tool[ToggleRequest]):
    name = "toggle"
    risk = Risk.READ
    request_type = ToggleRequest
    description = ToolDescription(when="тест", does="тест", returns="тест", refusals="тест")

    def _run(self, request: ToggleRequest) -> ToolResult:
        return ToolResult.success(**request.model_dump())


def run(capsys: pytest.CaptureFixture[str], *argv: str) -> dict[str, object]:
    command = ToolCommand(Toggle(), ToolDispatcher((Refusals,)))
    parser = argparse.ArgumentParser()
    command.configure(parser)
    command.run(parser.parse_args(argv))
    return json.loads(capsys.readouterr().out)


class TestToolCommand:
    def test_false_means_false(self, capsys: pytest.CaptureFixture[str]) -> None:
        """`bool("false")` — True: команда включала то, что просили выключить."""
        assert run(capsys, "нет", "1")["enabled"] is False
        assert run(capsys, "false", "1")["enabled"] is False
        assert run(capsys, "да", "1")["enabled"] is True

    def test_a_word_that_is_not_yes_or_no_is_refused(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit):
            run(capsys, "может", "1")

    def test_lists_take_several_values(self, capsys: pytest.CaptureFixture[str]) -> None:
        result = run(capsys, "да", "1", "2", "--tags", "a", "b")

        assert (result["ok"], result["targets"], result["tags"]) == (True, [1, 2], ["a", "b"])

    def test_optional_true_can_be_turned_off(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert run(capsys, "да", "1")["loud"] is True
        assert run(capsys, "да", "1", "--no-loud")["loud"] is False

    def test_complex_values_are_json(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert run(capsys, "да", "1", "--extra", '{"a": 2}')["extra"] == {"a": 2}

    def test_annotated_items_are_plain_strings(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Ревью 07.11.2026, №2: шаги `plan_create` — `list[Annotated[str, Field(...)]]`, и строка уходила в `json.loads`."""

        class Plan(Toggle):
            name = "plan_create"
            request_type = CreatePlanRequest  # pyright: ignore[reportAssignmentType, reportIncompatibleVariableOverride]

        command = ToolCommand(Plan(), ToolDispatcher((Refusals,)))
        parser = argparse.ArgumentParser()
        command.configure(parser)

        assert parser.parse_args(["Тесты", "Открыть проект", "Запустить тесты"]).steps == ["Открыть проект", "Запустить тесты"]
