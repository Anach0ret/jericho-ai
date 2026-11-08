"""Разные права (сервер, 23.10.2026): владельцу — всё с «да», остальным — не выше их предела; «да» предел не снимает."""

from jericho.core import Approval, ConfirmationGate, Risk, Tool, ToolDescription, ToolRequest, ToolResult
from jericho.core.conf.settings import Settings
from jericho.core.testing.fakes import Confirmations
from jericho.core.tools.dispatcher import ToolDispatcher
from jericho.core.tools.middleware import Refusals
from jericho.core.tools.policy import RiskPolicy

DESCRIPTION = ToolDescription(when="тест", does="тест", returns="тест", refusals="тест")


class State(Tool[ToolRequest]):
    name = "server_state"
    risk = Risk.READ
    description = DESCRIPTION
    request_type = ToolRequest

    def _run(self, request: ToolRequest) -> ToolResult:
        return ToolResult.success()


class Restart(State):
    name = "restart_container"
    risk = Risk.EFFECT
    approval = Approval.TOOL      # «да» спрашивает сама ручка — предел пользователя проверяется раньше

    def __init__(self) -> None:
        self.restarted = False

    def _run(self, request: ToolRequest) -> ToolResult:
        self.restarted = True
        return ToolResult.success()


def dispatcher(ceiling: Risk | None) -> ToolDispatcher:
    return ToolDispatcher((Refusals,), policy=RiskPolicy(ConfirmationGate(Confirmations(), "run-1"), ceiling=ceiling))


class TestUserRisk:
    def test_reader_reads_but_cannot_act(self) -> None:
        restart = Restart()

        assert dispatcher(Risk.READ).call(State(), {}).ok
        result = dispatcher(Risk.READ).call(restart, {})

        assert result.error == RiskPolicy.NOT_ALLOWED and (result.data["risk"], result.data["allowed"]) == ("effect", "read")
        assert not restart.restarted

    def test_owner_and_single_person_assistant_are_not_limited(self) -> None:
        assert dispatcher(Risk.EFFECT).call(Restart(), {}).ok
        assert dispatcher(None).call(Restart(), {}).ok

    def test_settings_name_the_ceiling_and_strangers_get_the_safest(self) -> None:
        settings = Settings(user_risk={"123456789": Risk.EFFECT})

        assert settings.user_risk.get("123456789", settings.default_user_risk) is Risk.EFFECT
        assert settings.user_risk.get("someone", settings.default_user_risk) is Risk.READ

    def test_risks_are_ordered(self) -> None:
        assert [risk.rank for risk in (Risk.READ, Risk.NAVIGATE, Risk.CHANGE, Risk.EFFECT)] == [0, 1, 2, 3]
