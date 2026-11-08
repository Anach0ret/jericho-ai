"""Политика риска держится диспетчером: ручка EFFECT без «да» не выполняется, без человека — не выполняется вовсе."""

from collections.abc import Mapping

from jericho.core import Approval, ConfirmationGate, Risk, Tool, ToolDescription, ToolRequest, ToolResult
from jericho.core.testing.fakes import Confirmations
from jericho.core.tools.confirm import Confirm
from jericho.core.tools.dispatcher import ToolDispatcher
from jericho.core.tools.middleware import Refusals
from jericho.core.tools.policy import RiskPolicy
from jericho.core.tools.session import CallSession


class SendRequest(ToolRequest):
    to: str


class Send(Tool[SendRequest]):
    """Отправка: сама о согласии не заботится — за неё спрашивает каркас."""

    name = "send"
    risk = Risk.EFFECT
    approval = Approval.ASK
    description = ToolDescription(when="Просят отправить.", does="Отправляет.", returns="Кому.", refusals="needs_confirm.")
    request_type = SendRequest

    def __init__(self) -> None:
        self.sent: list[str] = []

    def consent_summary(self, arguments: Mapping[str, object]) -> str:
        return f"отправить письмо {arguments['to']}"

    def _run(self, request: SendRequest) -> ToolResult:
        self.sent.append(request.to)
        return ToolResult.success(sent=request.to)


class SendOwn(Send):
    """Та же отправка, но согласие ручка спрашивает сама (здесь — никогда)."""

    name = "send_own"
    approval = Approval.TOOL


class Peek(Send):
    name = "peek"
    risk = Risk.READ


def run(store: Confirmations, run_id: str, attended: bool = True, allowed: tuple[str, ...] = ()) -> tuple[ToolDispatcher, Send, Confirm]:
    gate, session = ConfirmationGate(store, run_id, attended=attended), CallSession()
    dispatcher = ToolDispatcher([Refusals], session, policy=RiskPolicy(gate, allowed))
    send = Send()
    return dispatcher, send, Confirm(gate, dispatcher, [send], session)


class TestRiskPolicy:
    def test_effect_is_asked_by_the_framework_even_if_the_tool_never_asks(self) -> None:
        store = Confirmations()
        dispatcher, send, _ = run(store, "run-1")

        result = dispatcher.call(send, {"to": "boss@example.org"})
        pending = store.pending()

        assert result.error == "needs_confirm" and send.sent == []
        assert pending is not None and pending.summary == "отправить письмо boss@example.org"

    def test_yes_in_the_next_phrase_runs_exactly_that_call(self) -> None:
        store = Confirmations()
        run(store, "run-1")[0].call(Send(), {"to": "boss@example.org"})
        dispatcher, send, confirm = run(store, "run-2")
        ConfirmationGate(store, "run-2").user_said_yes()      # «да» пользователя слышит вход поручения

        assert dispatcher.call(confirm, {}).ok and send.sent == ["boss@example.org"]

    def test_without_a_person_effect_is_refused_before_the_tool_runs(self) -> None:
        store = Confirmations()
        dispatcher, send, _ = run(store, "task", attended=False)

        own = SendOwn()
        assert dispatcher.call(send, {"to": "a@b.c"}).error == RiskPolicy.NOBODY_TO_ASK
        assert dispatcher.call(own, {"to": "a@b.c"}).error == RiskPolicy.NOBODY_TO_ASK      # и та, что спрашивает сама
        assert send.sent == own.sent == [] and store.pending() is None

    def test_project_may_allow_a_named_effect_without_a_person(self) -> None:
        dispatcher, send, _ = run(Confirmations(), "task", attended=False, allowed=("send",))

        assert dispatcher.call(send, {"to": "report@example.org"}).ok and send.sent == ["report@example.org"]

    def test_tool_that_asks_itself_and_harmless_tools_pass(self) -> None:
        dispatcher = run(Confirmations(), "run-1")[0]

        assert dispatcher.call(SendOwn(), {"to": "a@b.c"}).ok
        assert dispatcher.call(Peek(), {"to": "a@b.c"}).ok

    def test_invalid_parameters_do_not_raise_a_question(self) -> None:
        store = Confirmations()

        assert run(store, "run-1")[0].call(Send(), {}).error == "invalid_parameters" and store.pending() is None
