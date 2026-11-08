import argparse
from datetime import timedelta
from pathlib import Path
from typing import cast

import pytest
from pydantic import ValidationError

from jericho.core.agent.context import PendingQuestion
from jericho.core.agent.handle_phrase import HandlePhrase
from jericho.core.assembly.installation import Installation
from jericho.core.services.adapters.memory_list import MemoryList
from jericho.core.services.confirmation import ConfirmationGate
from jericho.core.services.lock import Unlocked
from jericho.core.testing import FakeBackend, builder
from jericho.core.testing.fakes import Confirmations
from jericho.modules.dialogue.task_layer import Conversation
from jericho.modules.dialogue.testing import Memory
from jericho.modules.tasks.command import TaskCommand
from jericho.modules.tasks.entities import Deferred, DeferredKind, DeferredState
from jericho.modules.tasks.module import TasksModule
from jericho.modules.tasks.queue import DeferredQueue
from jericho.modules.tasks.settings import DeferredSettings, ScheduledCommand, ScheduledTask, TasksSettings
from jericho.modules.tasks.tests.fakes import START, Clock, Delivered, FakeRelaunch


def command(relaunch: FakeRelaunch, backend: FakeBackend, output: Delivered) -> TaskCommand:
    tasks = {"morning": ScheduledTask(text="сводка на сегодня")}
    return TaskCommand(tasks, HandlePhrase(builder(), backend, attended=relaunch.attended), {"morning": output}, relaunch)


class TestTaskCommand:
    def test_from_the_terminal_the_task_runs_again_without_a_person(self) -> None:
        relaunch, backend = FakeRelaunch(attended=True), FakeBackend({"status": "done", "message": "ок"})

        command(relaunch, backend, Delivered()).run(argparse.Namespace(task="morning"))

        assert relaunch.launched == [("task", "morning")]
        assert backend.asked == []

    def test_failed_relaunch_fails_the_command(self) -> None:
        with pytest.raises(SystemExit):
            command(FakeRelaunch(attended=True, code=1), FakeBackend(), Delivered()).run(argparse.Namespace(task="morning"))

    def test_without_a_person_the_model_is_told_so_and_the_reply_is_delivered(self) -> None:
        backend, output = FakeBackend({"status": "done", "message": "сводка готова"}), Delivered()

        command(FakeRelaunch(attended=False), backend, output).run(argparse.Namespace(task="morning"))

        assert HandlePhrase.UNATTENDED_NOTE in backend.asked[0][1]
        assert [(task, reply.message) for task, reply in output.replies] == [("сводка на сегодня", "сводка готова")]

    def test_failure_is_an_exit_code_for_the_timer(self) -> None:
        with pytest.raises(SystemExit):
            command(FakeRelaunch(attended=False), FakeBackend(error="boom"), Delivered()).run(argparse.Namespace(task="morning"))


    def test_refusal_is_an_exit_code_too(self) -> None:
        with pytest.raises(SystemExit):
            command(FakeRelaunch(attended=False), FakeBackend({"status": "refused", "message": "нельзя"}), Delivered()).run(argparse.Namespace(task="morning"))


class TestNobodyToAsk:
    def test_question_is_not_stored_and_cannot_be_answered_by_someone_else(self) -> None:
        store = Confirmations()

        consent = ConfirmationGate(store, "task-run", attended=False).consent("erase", {}, "стереть всё")

        assert not consent.granted and "nobody" in consent.notes()
        assert store.pending() is None

    def test_question_of_the_person_is_not_taken(self) -> None:
        store = Confirmations()
        ConfirmationGate(store, "voice-run").consent("erase", {}, "стереть всё")

        assert ConfirmationGate(store, "task-run", attended=False).grant() is None
        assert store.pending() is not None

    def test_prompt_does_not_show_the_question_of_the_person(self) -> None:
        store = Confirmations()
        ConfirmationGate(store, "voice-run").consent("erase", {}, "стереть всё")

        assert "стереть всё" not in PendingQuestion(store, attended=False).values()["pending_confirmation"]

    def test_task_is_not_part_of_the_conversation(self) -> None:
        memory = Memory()

        HandlePhrase(builder(), FakeBackend({"status": "done", "message": "ок"}), [Conversation(memory)], attended=False).execute("сводка")

        assert memory.exchanges == []

    def test_mark_reaches_the_tool_server(self) -> None:
        environment = {Installation.SETTINGS_VARIABLE: "demo.settings", Installation.UNATTENDED_VARIABLE: "1"}
        installation = Installation.discover(environment, Path("/home/u"), "python")

        assert not installation.attended
        assert installation.tool_server_environment("run")[Installation.UNATTENDED_VARIABLE] == "1"


def test_task_names_must_fit_the_command_line() -> None:
    with pytest.raises(ValidationError):
        TasksSettings(items={"Утро": ScheduledTask(text="сводка")})


class TestStatus:
    """Снимок для окна: что по расписанию, что ждёт срока и что уже сделано — свежее сверху."""

    def module(self, settings: TasksSettings, clock: Clock) -> TasksModule:
        module = TasksModule()
        module.settings = settings
        module.queue = DeferredQueue(MemoryList[Deferred](), Unlocked(), clock)
        return module

    def test_regular_waiting_and_done(self) -> None:
        clock = Clock()
        settings = TasksSettings(
            items={"morning": ScheduledTask(text="сводка на сегодня", schedule="*-*-* 08:00")},
            commands={"clean": ScheduledCommand(command=("files", "--clean"), schedule="daily")},
            deferred=DeferredSettings(enabled=True),
        )
        module = self.module(settings, clock)
        early = module.queue.add(DeferredKind.REMIND, "духовка", START)
        late = module.queue.add(DeferredKind.DO, "сводка почты", START + timedelta(minutes=5))
        module.queue.add(DeferredKind.REMIND, "позвонить", START + timedelta(hours=3))
        clock.now += timedelta(minutes=10)
        module.queue.finish(early, DeferredState.DONE, "напомнил")
        clock.now += timedelta(minutes=1)
        module.queue.finish(late, DeferredState.FAILED, "сеть")

        status = module.status()

        assert status["regular"] == [
            {"name": "morning", "kind": "task", "text": "сводка на сегодня", "schedule": "*-*-* 08:00"},
            {"name": "clean", "kind": "command", "text": "files --clean", "schedule": "daily"},
        ]
        assert [item["text"] for item in cast(list[dict[str, str]], status["deferred"])] == ["позвонить"]
        history = cast(list[dict[str, str]], status["history"])
        assert [(item["text"], item["state"], item["outcome"]) for item in history] == [("сводка почты", "failed", "сеть"), ("духовка", "done", "напомнил")]

    def test_nothing_scheduled_is_an_empty_snapshot(self) -> None:
        assert self.module(TasksSettings(), Clock()).status() == {}
