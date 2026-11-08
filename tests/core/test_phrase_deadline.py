"""Один срок на всю фразу: запасной бэкенд, сервер ручек CLI и `confirm` после него ничего не начинают.

Ревью 02.11.2026, сводка №9: запасной `ToolLoop` начинал полный срок заново — ручка стартовала на 1,6 с при сроке 1 с.
Критика плана 07.11.2026, риск 1: сервер ручек звал диспетчер без срока — после `agent.timeout` ручка выполнялась.
"""

import os
import subprocess
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Self

import pytest

from jericho.backends.tool_loop.entities import CallAnswer, ModelTurn, ToolCall, ToolSpec
from jericho.backends.tool_loop.loop import ToolLoop
from jericho.backends.tool_loop.testing import DONE, Open
from jericho.core.agent.entities import BackendAnswer
from jericho.core.agent.fallback import FallbackBackend, NamedBackend
from jericho.core.agent.forms import Brief
from jericho.core.agent.handle_phrase import HandlePhrase
from jericho.core.agent.protocols import ModelTimeout, ModelUnavailable
from jericho.core.assembly.installation import Installation
from jericho.core.services.confirmation import ConfirmationGate
from jericho.core.services.phrase_deadline import PhraseDeadline
from jericho.core.services.program import Program
from jericho.core.services.runner import CommandTimeout, SubprocessRunner
from jericho.core.testing import Confirmations, FakeBackend, builder
from jericho.core.tools.confirm import Confirm
from jericho.core.tools.dispatcher import ToolDispatcher
from jericho.core.tools.middleware import Journal, Refusals
from jericho.core.tools.session import CallSession


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class SlowModel:
    """Модель, ход которой длится `takes` секунд по общим часам; без ходов — упирается в лимит."""

    name = "slow"

    def __init__(self, clock: Clock, takes: float, *turns: ModelTurn, unavailable: bool = False) -> None:
        self._clock, self._takes, self._turns, self._unavailable = clock, takes, list(turns), unavailable
        self.answers: list[list[CallAnswer]] = []

    def chat(self, system_prompt: str, phrase: str, tools: Sequence[ToolSpec]) -> Self:
        return self

    def turn(self, timeout: float) -> ModelTurn:
        self._clock.now += self._takes
        if self._unavailable:
            raise ModelUnavailable("usage limit")
        return self._turns.pop(0)

    def answer(self, answers: Sequence[CallAnswer]) -> None:
        self.answers.append(list(answers))

    def remind(self, text: str) -> None:
        pass


class NoActions:
    def done(self) -> tuple[str, ...]:
        return ()


def open_call(what: str) -> ModelTurn:
    return ModelTurn((ToolCall("c1", "open", {"what": what}),))


class TestFallbackKeepsTheDeadline:
    def test_spare_loop_does_not_start_a_tool_after_the_phrase_deadline(self) -> None:
        clock, tool = Clock(), Open()
        deadline = PhraseDeadline(seconds=1.0, clock=clock)
        dispatcher = ToolDispatcher([Journal, Refusals], phrase=deadline)

        def loop(model: SlowModel) -> ToolLoop:
            return ToolLoop(model, [tool], dispatcher, Brief().schema(), timeout=1.0, max_turns=3, clock=clock, phrase=deadline)

        main = SlowModel(clock, 0.8, unavailable=True)
        spare = SlowModel(clock, 0.8, open_call("ютуб"), ModelTurn((ToolCall("c2", "reply", DONE),)))
        chain = FallbackBackend([NamedBackend("main", loop(main)), NamedBackend("spare", loop(spare))], NoActions(), deadline=deadline)
        deadline.start()

        with pytest.raises(ModelTimeout):
            chain.ask("промпт", "открой ютуб")

        assert tool.opened == []      # ход пришёл на 1,6 с: ручка не начата

    def test_spare_is_not_asked_once_the_deadline_passed(self) -> None:
        clock = Clock()
        deadline = PhraseDeadline(seconds=1.0, clock=clock)

        class Late:
            def ask(self, system_prompt: str, phrase: str) -> BackendAnswer:
                clock.now += 1.5
                raise ModelUnavailable("limit")

        spare = FakeBackend(DONE)
        chain = FallbackBackend([NamedBackend("main", Late()), NamedBackend("spare", spare)], NoActions(), deadline=deadline)
        deadline.start()

        with pytest.raises(ModelTimeout, match="out of time"):
            chain.ask("промпт", "фраза")
        assert spare.asked == []


class TestDispatcherKeepsTheDeadline:
    def test_no_tool_starts_after_the_deadline(self) -> None:
        clock, tool = Clock(), Open()
        deadline = PhraseDeadline(seconds=1.0, clock=clock)
        deadline.start()
        clock.now += 2

        result = ToolDispatcher([Journal, Refusals], phrase=deadline).call(tool, {"what": "ютуб"})

        assert result.error == ToolDispatcher.PHRASE_DEADLINE_PASSED and tool.opened == []

    def test_tool_server_gets_the_deadline_of_the_phrase_that_started_it(self) -> None:
        """Сервер ручек — другой процесс: срок приходит моментом в окружении, а не «сколько-то секунд»."""
        clock = Clock()
        phrase = PhraseDeadline(seconds=1.0, clock=clock)
        phrase.start()
        server = PhraseDeadline.from_environment(phrase.environment(), seconds=90.0)
        server.start()     # даже если сервер вдруг начнёт свою фразу — не позже срока родителя

        left = server.left()
        assert left is not None and left <= 1.0
        tool = Open()
        server_dispatcher = ToolDispatcher([Journal, Refusals], phrase=PhraseDeadline.from_environment({PhraseDeadline.VARIABLE: "1.0"}))
        assert server_dispatcher.call(tool, {"what": "ютуб"}).error == ToolDispatcher.PHRASE_DEADLINE_PASSED
        assert tool.opened == []

    def test_confirm_after_the_deadline_does_nothing(self) -> None:
        clock, store, tool = Clock(), Confirmations(), Open()
        ConfirmationGate(store, "run-1").consent("open", {"what": "ютуб"}, "открыть ютуб")
        gate, deadline = ConfirmationGate(store, "run-2"), PhraseDeadline(seconds=1.0, clock=clock)
        dispatcher = ToolDispatcher([Journal, Refusals], phrase=deadline)
        deadline.start()
        clock.now += 2

        gate.user_said_yes()
        result = dispatcher.call(Confirm(gate, dispatcher, [tool], CallSession()), {})

        assert result.error == ToolDispatcher.PHRASE_DEADLINE_PASSED and tool.opened == []

    def test_without_a_phrase_there_is_no_deadline(self) -> None:
        """Вызов руками из терминала: фразы нет — и срока фразы нет."""
        assert ToolDispatcher([Journal, Refusals]).call(Open(), {"what": "ютуб"}).ok


class TestPhraseStartsTheDeadline:
    def test_the_phrase_sets_the_deadline_and_clears_it_after(self) -> None:
        clock = Clock()
        deadline = PhraseDeadline(seconds=90.0, clock=clock)
        seen: list[float | None] = []

        class Backend(FakeBackend):
            def ask(self, system_prompt: str, phrase: str) -> BackendAnswer:
                seen.append(deadline.left())
                return super().ask(system_prompt, phrase)

        HandlePhrase(builder(), Backend(DONE), deadline=deadline).execute("открой ютуб")

        assert seen == [90.0] and deadline.left() is None


class TestModelProgramKeepsTheDeadline:
    def test_claude_or_codex_is_not_started_after_the_deadline(self) -> None:
        clock = Clock()
        deadline = PhraseDeadline(seconds=1.0, clock=clock)
        deadline.start()
        clock.now += 2

        with pytest.raises(CommandTimeout, match="out of time"):
            SubprocessRunner(timeout=90, deadline=deadline).run(["true"], reads=True)


class TestSeparateLaunchHasItsOwnDeadline:
    """Ревью 07.11.2026, №1: `plan_run` из сервера ручек отделял запуск, а срок исходной фразы шёл с ним — план из
    нескольких фраз упирался в её остаток, первый шаг мог не начаться вовсе."""

    def test_detached_launch_does_not_inherit_the_phrase_deadline(self, tmp_path: Path) -> None:
        program = Program("p", (sys.executable, "-c"), {}, tmp_path, tmp_path)
        command = program.detached("import os; print(os.environ.get('JERICHO_DEADLINE'), os.environ.get('JERICHO_RUN'))")
        environment = {**os.environ, PhraseDeadline.VARIABLE: repr(time.time() - 1), Program.RUN_VARIABLE: "run-1"}

        printed = subprocess.run(command, env=environment, capture_output=True, text=True, check=True, encoding="utf-8").stdout.split()

        assert printed == ["None", "None"]

    def test_unattended_relaunch_starts_without_the_old_deadline(self, tmp_path: Path) -> None:
        installation = Installation.discover(
            {Installation.SETTINGS_VARIABLE: "tests.core.sample_settings", PhraseDeadline.VARIABLE: "1.0"}, tmp_path, sys.executable
        )

        assert PhraseDeadline.VARIABLE not in installation.unattended_environment()

    def test_steps_of_a_long_plan_each_get_a_full_deadline(self) -> None:
        """Каждая фраза плана — свой срок: суммарно шаги идут дольше одного `agent.timeout`."""
        clock = Clock()
        deadline = PhraseDeadline.from_environment({}, seconds=1.0)
        deadline._clock = clock  # pyright: ignore[reportPrivateUsage]
        lefts = []
        for _ in range(3):
            deadline.start()
            clock.now += 0.8
            lefts.append(deadline.left())
            deadline.stop()

        assert lefts == [pytest.approx(0.2)] * 3
