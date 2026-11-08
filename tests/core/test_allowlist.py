from collections.abc import Sequence

import pytest

from jericho.core import Allowlist, AllowlistTool, CommandRule, Risk, ToolDescription, ToolRefusal
from jericho.core.testing import execute

PLAYER = Allowlist(
    tool="player",
    risk=Risk.CHANGE,
    program="playerctl",
    description=ToolDescription(when="Музыка.", does="Управляет плеером.", returns="Ничего.", refusals="command_not_allowed."),
    command_description="Команда плееру.",
    rules=(*CommandRule.reading("status", "metadata", flags=("--all",)), *CommandRule.changing("volume", "up", "down")),
)


class Console:
    def __init__(self) -> None:
        self.ran: list[tuple[list[str], bool]] = []

    def run(self, arguments: Sequence[str], rule: CommandRule) -> object:
        self.ran.append((list(arguments), rule.reads))
        return {"playing": True} if rule.reads else None


class TestAllowlist:
    @pytest.mark.parametrize("command", ["status", "status --all", "volume up", "volume down 5", "playerctl status"])
    def test_listed_commands_pass(self, command: str) -> None:
        PLAYER.rule_for(PLAYER.parse(command))

    @pytest.mark.parametrize(
        ("command", "error"),
        [
            ("stop", "command_not_allowed"),
            ("volume", "command_not_allowed"),
            ("volume mute", "command_not_allowed"),
            ("status --follow", "command_not_allowed"),
            ("status ; rm -rf ~", "forbidden_characters"),
            ("volume up;", "forbidden_characters"),
            ("", "empty_command"),
            ("volume 'up", "unparsable_command"),
        ],
    )
    def test_everything_else_is_refused(self, command: str, error: str) -> None:
        with pytest.raises(ToolRefusal, match=error):
            PLAYER.rule_for(PLAYER.parse(command))

    def test_refusal_lists_what_is_allowed_for_the_same_command(self) -> None:
        with pytest.raises(ToolRefusal) as refusal:
            PLAYER.rule_for(["volume", "mute"])

        assert refusal.value.details == {"allowed": ["volume down", "volume up"]}

    def test_unknown_command_gets_the_whole_list(self) -> None:
        with pytest.raises(ToolRefusal) as refusal:
            PLAYER.rule_for(["stop"])

        assert refusal.value.details == {"allowed": ["metadata", "status", "volume down", "volume up"]}

    def test_rule_knows_whether_the_command_only_reads(self) -> None:
        assert PLAYER.rule_for(["status"]).reads and not PLAYER.rule_for(["volume", "up"]).reads


class TestAllowlistTool:
    def test_tool_takes_its_name_description_and_parameter_from_the_list(self) -> None:
        tool = AllowlistTool(PLAYER, Console())

        assert (tool.name, tool.description) == ("player", PLAYER.description)
        assert tool.request_type.tool_schema()["properties"] == {"command": {"description": "Команда плееру.", "type": "string"}}

    def test_reading_command_returns_what_the_console_answered(self) -> None:
        console = Console()

        result = execute(AllowlistTool(PLAYER, console), {"command": "playerctl status"})

        assert result.to_dict() == {"ok": True, "result": {"playing": True}} and console.ran == [(["status"], True)]

    def test_changing_command_reports_what_was_done(self) -> None:
        console = Console()

        result = execute(AllowlistTool(PLAYER, console), {"command": "volume up 5"})

        assert result.to_dict() == {"ok": True, "done": "volume up 5"} and console.ran == [(["volume", "up", "5"], False)]

    def test_refused_command_never_reaches_the_console(self) -> None:
        console = Console()

        result = execute(AllowlistTool(PLAYER, console), {"command": "stop"})

        assert result.error == "command_not_allowed" and console.ran == []
