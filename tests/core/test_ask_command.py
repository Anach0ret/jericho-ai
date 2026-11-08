import argparse
import io

import pytest

from jericho.core.agent.entities import AgentReply, ReplyStatus
from jericho.core.agent.handle_phrase import HandlePhrase
from jericho.core.interfaces.cli.agent_commands import AskCommand
from jericho.core.testing import FakeBackend, builder


class Output:
    def __init__(self) -> None:
        self.delivered: list[tuple[str, AgentReply]] = []

    def deliver(self, task: str, reply: AgentReply) -> None:
        self.delivered.append((task, reply))


def ask(phrase: str | None) -> tuple[Output, FakeBackend]:
    output, backend = Output(), FakeBackend({"status": "done", "message": "Открыл YouTube"})
    command = AskCommand(HandlePhrase(builder(), backend), output)
    parser = argparse.ArgumentParser()
    command.configure(parser)
    command.run(parser.parse_args([] if phrase is None else [phrase]))
    return output, backend


class TestAskCommand:
    def test_phrase_from_the_command_line(self) -> None:
        output, _ = ask("открой ютуб")

        assert output.delivered == [("открой ютуб", AgentReply(ReplyStatus.DONE, "Открыл YouTube"))]

    def test_phrase_from_stdin_for_programs(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Окно на панели отдаёт текст через stdin: строку команды видит любой процесс машины."""
        monkeypatch.setattr("sys.stdin", io.StringIO("  открой ютуб\n"))

        _, backend = ask(None)

        assert backend.asked[0][1] == "открой ютуб"

    def test_empty_stdin_reaches_no_model(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("sys.stdin", io.StringIO("   "))

        with pytest.raises(SystemExit):
            ask("-")
