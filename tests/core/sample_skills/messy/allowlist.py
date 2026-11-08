from jericho.core import Allowlist, CommandRule, Risk, ToolDescription

PLAYER = Allowlist(
    tool="player",
    risk=Risk.READ,
    program="playerctl",
    description=ToolDescription(when="Музыка.", does="Плеер.", returns="Ничего.", refusals="Нет."),
    command_description="Команда.",
    rules=CommandRule.reading("status"),
)
