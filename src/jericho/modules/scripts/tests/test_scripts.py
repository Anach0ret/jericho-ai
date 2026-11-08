import argparse
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from jericho.core import Approval, ConfirmationGate, Risk, Tool, ToolDescription, ToolRequest, ToolResult
from jericho.core.agent.entities import AgentReply, ReplyStatus
from jericho.core.checks.base import Project
from jericho.core.conf.settings import Settings
from jericho.core.modules.registry import InstalledModules
from jericho.core.skills.registry import InstalledSkills
from jericho.core.testing.fakes import Confirmations, execute
from jericho.core.tools.catalog import ToolCatalog
from jericho.core.tools.dispatcher import ToolDispatcher
from jericho.core.tools.middleware import Refusals
from jericho.core.tools.policy import RiskPolicy
from jericho.core.tools.result import ToolRefusal
from jericho.core.tools.session import CallSession
from jericho.modules.scripts.checks import ScriptsAreValid
from jericho.modules.scripts.command import RunCommand
from jericho.modules.scripts.module import ScriptsModule
from jericho.modules.scripts.runner import ScriptRunner
from jericho.modules.scripts.settings import Script, ScriptsSettings, Step
from jericho.modules.scripts.tools import RunScript

DESCRIPTION = ToolDescription(when="тест", does="тест", returns="тест", refusals="тест")


class OpenRequest(ToolRequest):
    name: str


class Open(Tool[OpenRequest]):
    name = "open_project"
    risk = Risk.NAVIGATE
    description = DESCRIPTION
    request_type = OpenRequest
    skill = "desktop"

    def __init__(self, fails: str = "") -> None:
        self.opened: list[str] = []
        self._fails = fails

    def _run(self, request: OpenRequest) -> ToolResult:
        if request.name == self._fails:
            raise ToolRefusal("project_not_found", detail=f"нет проекта {request.name}")
        self.opened.append(request.name)
        return ToolResult.success(detail=f"открыл {request.name}")


class Close(Tool[ToolRequest]):
    name = "close_windows"
    risk = Risk.EFFECT
    approval = Approval.ASK
    description = DESCRIPTION
    request_type = ToolRequest

    def _run(self, request: ToolRequest) -> ToolResult:
        return ToolResult.success()


def catalog(*tools: Tool[Any]) -> ToolCatalog:
    """Каталог с настоящим диспетчером: слои, политика риска — как у модели. Навык не загружен — каталог загрузит."""
    dispatcher = ToolDispatcher((Refusals,), CallSession(), policy=RiskPolicy(ConfirmationGate(Confirmations(), "run-1")))
    filled = ToolCatalog()
    filled.fill(tools, dispatcher)
    return filled


WORK = Script(title="Рабочее место", steps=(
    Step(tool="open_project", arguments={"name": "jericho"}), Step(tool="open_project", arguments={"name": "portfolio"}),
))
LECTURE = Script(title="Записать на лекцию", steps=(Step(phrase="запиши меня на ближайшую лекцию курса"),))


class TestSettings:
    def test_step_is_a_tool_or_a_phrase(self) -> None:
        with pytest.raises(ValidationError):
            Step(tool="open_project", phrase="открой")
        with pytest.raises(ValidationError):
            Step()

    def test_name_is_one_word(self) -> None:
        with pytest.raises(ValidationError):
            ScriptsSettings(items={"рабочее место": WORK})


class TestRunner:
    def test_steps_go_through_the_dispatcher_in_order(self) -> None:
        tool = Open()

        outcome = ScriptRunner(catalog(tool)).run("work", WORK)

        assert outcome.ok and tool.opened == ["jericho", "portfolio"]
        assert outcome.summary() == "Готово: Рабочее место — открыл jericho; открыл portfolio"

    def test_stops_at_the_first_failure(self) -> None:
        tool = Open(fails="jericho")

        outcome = ScriptRunner(catalog(tool)).run("work", WORK)

        assert not outcome.ok and tool.opened == []
        assert outcome.summary() == "Не до конца: Рабочее место — шаг 1 из 2 (open_project): нет проекта jericho"

    def test_effect_step_is_refused_by_the_policy_without_yes(self) -> None:
        script = Script(title="Уборка", steps=(Step(tool="close_windows"),))

        assert not ScriptRunner(catalog(Close())).run("clean", script).ok

    def test_phrase_goes_to_the_model(self) -> None:
        asked: list[str] = []

        def ask(phrase: str) -> AgentReply:
            asked.append(phrase)
            return AgentReply(ReplyStatus.DONE, "Зарегистрировал на «Проект 8»")

        outcome = ScriptRunner(catalog(), ask).run("lecture", LECTURE)

        assert outcome.ok and asked == ["запиши меня на ближайшую лекцию курса"]
        assert "Зарегистрировал" in outcome.summary()

    def test_question_from_the_model_waits_rather_than_fails(self) -> None:
        def ask(phrase: str) -> AgentReply:
            return AgentReply(ReplyStatus.CLARIFY, "Ближайшая — «Проект 8» в 14:30. Зарегистрировать?")

        outcome = ScriptRunner(catalog(), ask).run("lecture", LECTURE)

        assert not outcome.ok and outcome.waiting
        assert outcome.summary() == "Ждёт ответа: Записать на лекцию — Ближайшая — «Проект 8» в 14:30. Зарегистрировать?"

    def test_phrase_without_a_model_fails(self) -> None:
        assert not ScriptRunner(catalog()).run("lecture", LECTURE).ok


class TestRunScript:
    def test_runs_by_name(self) -> None:
        tool = Open()

        result = execute(RunScript({"work": WORK}, ScriptRunner(catalog(tool))), {"name": "work"})

        assert result.ok and tool.opened == ["jericho", "portfolio"]

    def test_script_with_a_phrase_is_left_to_the_model(self) -> None:
        result = execute(RunScript({"lecture": LECTURE}, ScriptRunner(catalog())), {"name": "lecture"})

        assert result.error == "uses_model" and result.data["steps"] == [{"phrase": "запиши меня на ближайшую лекцию курса"}]

    def test_mixed_script_keeps_its_tool_steps_in_order(self) -> None:
        """Раньше модели уходили только фразы: открытие проекта перед ними терялось (ревью 02.11.2026, П3a №11)."""
        mixed = Script(title="Задача", steps=(Step(tool="open_project", arguments={"name": "x"}), Step(phrase="сделай задачу")))

        result = execute(RunScript({"task": mixed}, ScriptRunner(catalog())), {"name": "task"})

        assert result.data["steps"] == [{"tool": "open_project", "arguments": {"name": "x"}}, {"phrase": "сделай задачу"}]

    def test_only_known_names(self) -> None:
        assert execute(RunScript({"work": WORK}, ScriptRunner(catalog())), {"name": "gym"}).error == "invalid_parameters"


class TestRunCommand:
    def test_failed_script_exits_with_an_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        command = RunCommand({"work": WORK}, ScriptRunner(catalog(Open(fails="jericho"))))
        parser = argparse.ArgumentParser()
        command.configure(parser)

        with pytest.raises(SystemExit):
            command.run(parser.parse_args(["work"]))
        assert "Не до конца" in capsys.readouterr().out


class WithScripts(Settings):
    scripts: ScriptsSettings = ScriptsSettings(items={
        "work": WORK,
        "typo": Script(title="Опечатка", steps=(Step(tool="open_projekt", arguments={"name": "x"}),)),
        "clean": Script(title="Уборка", steps=(Step(tool="close_windows"),)),
        "bad": Script(title="Без имени", steps=(Step(tool="open_project", arguments={}),)),
    })


class Tools(ScriptsModule):
    def tools(self) -> tuple[Tool[Any], ...]:
        return (Open(), Close())


class TestCheck:
    def test_finds_unknown_tool_effect_and_bad_arguments(self) -> None:
        project = Project(Path("."), InstalledSkills([]), modules=InstalledModules([("tests.tools", Tools())]), settings=WithScripts())

        found = {message.where: message.text for message in ScriptsAreValid().run(project)}

        assert set(found) == {"scripts.typo", "scripts.clean", "scripts.bad"}
        assert "open_projekt" in found["scripts.typo"] and "EFFECT" in found["scripts.clean"] and "name" in found["scripts.bad"]
