import json
from collections.abc import Sequence
from pathlib import Path

import pytest

from jericho.backends.claude_cli.client import ClaudeCliBackend
from jericho.core.agent.model_reply import ModelReply
from jericho.core.agent.protocols import AgentBackendError, ModelTimeout, ModelUnavailable
from jericho.core.services.phrase_deadline import PhraseDeadline
from jericho.core.services.runner import CommandError, CommandTimeout


class FakeRunner:
    def __init__(self, output: str = "", error: CommandError | None = None) -> None:
        self.command: list[str] = []
        self.stdin: str | None = None
        self._output = output
        self._error = error

    def run(
        self, command: Sequence[str], stdin: str | None = None, *, reads: bool = False, dry_answer: str = ""
    ) -> str:
        if self._error is not None:
            raise self._error
        self.command, self.stdin = list(command), stdin
        return self._output

    def launch(self, command: Sequence[str]) -> None:
        self.run(command)


def backend(runner: FakeRunner) -> ClaudeCliBackend:
    return ClaudeCliBackend(
        runner=runner,
        executable=Path("/bin/claude"),
        model="haiku",
        mcp_command=["/venv/python", "-m", "jericho", "mcp"],
        tools=["open_project"],
        reply_schema=ModelReply.json_schema(),
        mcp_environment={"JERICHO_CONFIGURATION": "DryRun"},
    )


class TestClaudeCliBackend:
    def test_runs_claude_with_only_our_tools_and_reads_the_answer(self) -> None:
        runner = FakeRunner(json.dumps({
            "is_error": False, "num_turns": 3, "duration_ms": 4100, "total_cost_usd": 0.002,
            "modelUsage": {"claude-haiku-5-5": {}},
            "structured_output": {"status": "done", "message": "Открыл portfolio"},
        }))

        answer = backend(runner).ask("ПРОМПТ", "открой портфолио")

        command = runner.command
        assert runner.stdin == "открой портфолио" and "открой портфолио" not in command
        assert command[:2] == ["/bin/claude", "-p"]
        assert command[command.index("--system-prompt") + 1] == "ПРОМПТ"
        assert command[command.index("--tools") + 1] == ""

        assert command[command.index("--allowedTools") + 1] == "mcp__jericho__open_project"
        assert "--strict-mcp-config" in command
        assert json.loads(command[command.index("--mcp-config") + 1]) == {
            "mcpServers": {
                "jericho": {
                    "command": "/venv/python",
                    "args": ["-m", "jericho", "mcp"],
                    "env": {"JERICHO_CONFIGURATION": "DryRun"},
                }
            }
        }
        assert answer.structured == {"status": "done", "message": "Открыл portfolio"}
        assert answer.meta == {"duration_ms": 4100, "num_turns": 3, "total_cost_usd": 0.002, "models": ["claude-haiku-5-5"]}

    def test_builtin_tools_are_allowed_only_by_name(self) -> None:
        runner = FakeRunner(json.dumps({"structured_output": {"status": "done", "message": "Открыл"}}))
        search = ClaudeCliBackend(
            runner=runner,
            executable=Path("/bin/claude"),
            model="haiku",
            mcp_command=["/venv/python", "-m", "jericho", "mcp"],
            tools=["open_url"],
            reply_schema=ModelReply.json_schema(),
            builtin_tools=["WebSearch"],
        )

        search.ask("ПРОМПТ", "открой последний выпуск")

        command = runner.command
        allowed = command[command.index("--allowedTools") + 1 : command.index("--setting-sources")]
        assert command[command.index("--tools") + 1] == "WebSearch"
        assert allowed == ["WebSearch", "mcp__jericho__open_url"]

    @pytest.mark.parametrize("output", ["не json", json.dumps({"is_error": True, "result": "limit"}), "[]"])
    def test_bad_output_is_a_backend_error(self, output: str) -> None:
        with pytest.raises(AgentBackendError):
            backend(FakeRunner(output)).ask("ПРОМПТ", "фраза")

    @pytest.mark.parametrize("result", [
        {"is_error": True, "result": "Claude AI usage limit reached|1760000000"},
        {"is_error": True, "duration_ms": 900, "num_turns": 1, "total_cost_usd": 0, "session_id": "x" * 300,
         "result": "You've hit your session limit · resets 5pm (Europe/Berlin)"},     # причина дальше 300 знаков
        {"is_error": True, "api_error_status": 529, "result": "API Error: Overloaded"},
    ])
    def test_subscription_limit_is_model_unavailable(self, result: dict[str, object]) -> None:
        """Лимит подписки — не поломка: поручение может взять запасной бэкенд."""
        with pytest.raises(ModelUnavailable):
            backend(FakeRunner(json.dumps(result))).ask("ПРОМПТ", "фраза")

    def test_other_errors_are_not_model_unavailable(self) -> None:
        with pytest.raises(AgentBackendError) as raised:
            backend(FakeRunner(json.dumps({"is_error": True, "result": "invalid model name"}))).ask("ПРОМПТ", "фраза")
        assert not isinstance(raised.value, ModelUnavailable)

    def test_process_out_of_time_is_a_timeout(self) -> None:
        with pytest.raises(ModelTimeout, match="no answer"):
            backend(FakeRunner(error=CommandTimeout("no answer in 90 s"))).ask("ПРОМПТ", "фраза")

    def test_reason_of_a_failed_run_is_read_from_its_output(self) -> None:
        """Журнал 29.10.2026: `claude` вышел с кодом 1, причина была в JSON на выводе, а в журнал попали только счётчики."""
        result = {"type": "result", "subtype": "error_max_turns", "is_error": True, "usage": {"input_tokens": 10} | {
            f"counter_{number}": number for number in range(40)}, "result": "Reached maximum number of turns"}
        failure = CommandError("exit code 1: {...", output=json.dumps(result))

        with pytest.raises(AgentBackendError, match="error_max_turns: Reached maximum number of turns"):
            backend(FakeRunner(error=failure)).ask("ПРОМПТ", "фраза")

    def test_limit_in_the_output_of_a_failed_run_is_model_unavailable(self) -> None:
        output = json.dumps({"is_error": True, "session_id": "x" * 300, "result": "Claude AI usage limit reached"})

        with pytest.raises(ModelUnavailable):
            backend(FakeRunner(error=CommandError("exit code 1", output=output))).ask("ПРОМПТ", "фраза")

    def test_failed_run_without_output_keeps_the_runner_message(self) -> None:
        with pytest.raises(AgentBackendError, match="exit code 2: no such option"):
            backend(FakeRunner(error=CommandError("exit code 2: no such option"))).ask("ПРОМПТ", "фраза")


class TestDeadline:
    def test_tool_server_gets_the_phrase_deadline_of_this_run(self) -> None:
        """Критика плана 07.11.2026, риск 1: сервер ручек — другой процесс; срок фразы он узнаёт из окружения."""
        deadline = PhraseDeadline(seconds=90.0, clock=lambda: 1000.0)
        deadline.start()
        runner = FakeRunner(json.dumps({"is_error": False, "structured_output": {"status": "done", "message": "ок"}}))
        claude = ClaudeCliBackend(
            runner=runner, executable=Path("/bin/claude"), model="haiku", mcp_command=["/venv/python", "-m", "jericho", "mcp"],
            tools=["open_project"], reply_schema=ModelReply.json_schema(), mcp_environment={"JERICHO_CONFIGURATION": "DryRun"},
            deadline=deadline,
        )

        claude.ask("ПРОМПТ", "открой")

        config = json.loads(runner.command[runner.command.index("--mcp-config") + 1])
        assert config["mcpServers"]["jericho"]["env"] == {"JERICHO_CONFIGURATION": "DryRun", PhraseDeadline.VARIABLE: "1090.0"}
