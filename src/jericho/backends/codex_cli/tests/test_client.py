import json
from collections.abc import Sequence
from pathlib import Path

import pytest

from jericho.backends.codex_cli.client import CodexCliBackend, strict_schema, toml_value
from jericho.core.agent.model_reply import ModelReply
from jericho.core.agent.protocols import AgentBackendError, ModelTimeout, ModelUnavailable
from jericho.core.services.phrase_deadline import PhraseDeadline
from jericho.core.services.runner import CommandError, CommandTimeout


class FakeRunner:
    def __init__(self, output: str = "", error: CommandError | None = None) -> None:
        self.command: list[str] = []
        self.stdin: str | None = None
        self.schema: dict[str, object] = {}
        self._output = output
        self._error = error

    def run(self, command: Sequence[str], stdin: str | None = None, *, reads: bool = False, dry_answer: str = "") -> str:
        self.command, self.stdin = list(command), stdin
        self.schema = json.loads(Path(self.command[self.command.index("--output-schema") + 1]).read_text(encoding="utf-8"))
        if self._error is not None:
            raise self._error
        return self._output

    def launch(self, command: Sequence[str]) -> None:
        self.run(command)


def events(*items: dict[str, object]) -> str:
    return "\n".join(json.dumps(item, ensure_ascii=False) for item in items)


def message(text: str) -> dict[str, object]:
    return {"type": "item.completed", "item": {"type": "agent_message", "text": text}}


ANSWER = message(json.dumps({"status": "done", "message": "Открыл portfolio", "options": []}, ensure_ascii=False))
CALL = {"type": "item.completed", "item": {"type": "mcp_tool_call", "server": "jericho", "tool": "open_project", "status": "completed"}}
USAGE = {"type": "turn.completed", "usage": {"input_tokens": 32000, "cached_input_tokens": 16000, "output_tokens": 120}}


def backend(runner: FakeRunner) -> CodexCliBackend:
    return CodexCliBackend(
        runner=runner, executable=Path("/bin/codex"), model="gpt-6.1-sol", reasoning_effort="low",
        mcp_command=["/venv/python", "-m", "jericho", "mcp"], tools=["open_project", "close_windows"],
        reply_schema=ModelReply.json_schema(), mcp_environment={"JERICHO_CONFIGURATION": "DryRun"},
        disabled_features=("shell_tool", "plugins"),
        inherited={"HYPRLAND_INSTANCE_SIGNATURE": "abc", "WAYLAND_DISPLAY": "wayland-1", "JERICHO_CONFIGURATION": "Live"},
    )


def option(command: list[str], prefix: str) -> str:
    """Значение `-c prefix=…` из команды."""
    return next(value[len(prefix) + 1:] for value in command if value.startswith(prefix + "="))


class TestCommand:
    def test_runs_codex_isolated_from_the_owners_setup_with_only_our_server(self) -> None:
        runner = FakeRunner(events(CALL, ANSWER, USAGE))

        backend(runner).ask("ПРОМПТ", "открой портфолио")

        command = runner.command
        assert command[:3] == [str(Path("/bin/codex")), "exec", "--json"] and command[-1] == "-"
        assert runner.stdin == "открой портфолио" and "открой портфолио" not in command
        for flag in ("--ignore-user-config", "--ignore-rules", "--ephemeral"):
            assert flag in command
        assert command[command.index("--sandbox") + 1] == "read-only" and 'approval_policy="never"' in command
        assert command[command.index("--disable"):command.index("--disable") + 4] == ["--disable", "shell_tool", "--disable", "plugins"]
        assert option(command, "developer_instructions") == '"ПРОМПТ"'
        assert option(command, "mcp_servers.jericho.args") == '["-m", "jericho", "mcp"]'
        assert option(command, "mcp_servers.jericho.env") == '{"JERICHO_CONFIGURATION" = "DryRun"}'

    def test_tool_server_inherits_this_environment_and_our_variables_win(self) -> None:
        """Без HYPRLAND_INSTANCE_SIGNATURE ручки окон не видят Hyprland; вариант настроек — тот, что задал каркас."""
        runner = FakeRunner(events(ANSWER))

        backend(runner).ask("П", "ф")

        assert option(runner.command, "mcp_servers.jericho.env_vars") == '["HYPRLAND_INSTANCE_SIGNATURE", "WAYLAND_DISPLAY"]'
        assert option(runner.command, "mcp_servers.jericho.env") == '{"JERICHO_CONFIGURATION" = "DryRun"}'

    def test_tool_server_gets_the_phrase_deadline_of_this_run(self) -> None:
        """Критика плана 07.11.2026, риск 1: срок фразы — серверу ручек, при каждом запуске свой."""
        runner, deadline = FakeRunner(events(ANSWER)), PhraseDeadline(seconds=90.0, clock=lambda: 1000.0)
        codex = backend(runner)
        codex._deadline = deadline  # pyright: ignore[reportPrivateUsage]
        deadline.start()

        codex.ask("П", "ф")

        assert option(runner.command, "mcp_servers.jericho.env") == '{"JERICHO_CONFIGURATION" = "DryRun", "JERICHO_DEADLINE" = "1090.0"}'

    def test_our_tools_need_no_approval_of_codex(self) -> None:
        """Согласие держит Jericho; одобрение codex при approval_policy="never" отклонило бы каждую меняющую ручку."""
        runner = FakeRunner(events(ANSWER))

        backend(runner).ask("П", "ф")

        assert option(runner.command, "mcp_servers.jericho.tools.open_project.approval_mode") == '"approve"'
        assert option(runner.command, "mcp_servers.jericho.tools.close_windows.approval_mode") == '"approve"'

    def test_working_folder_is_an_empty_temporary_one_and_is_removed(self) -> None:
        runner = FakeRunner(events(ANSWER))

        backend(runner).ask("П", "ф")

        folder = Path(runner.command[runner.command.index("--cd") + 1])
        assert folder.name.startswith("jericho-codex-") and not folder.exists()

    def test_reply_schema_is_strict(self) -> None:
        runner = FakeRunner(events(ANSWER))

        backend(runner).ask("П", "ф")

        assert sorted(runner.schema["required"]) == ["message", "options", "status"]   # pyright: ignore[reportArgumentType]


class TestAnswer:
    def test_last_message_is_the_reply_and_calls_are_counted(self) -> None:
        answer = backend(FakeRunner(events(message("думаю…"), CALL, CALL, ANSWER, USAGE))).ask("П", "ф")

        assert answer.structured == {"status": "done", "message": "Открыл portfolio", "options": []}
        assert answer.meta == {"models": ["gpt-6.1-sol"], "num_turns": 3, "input_tokens": 32000, "cached_tokens": 16000, "output_tokens": 120}

    def test_settings_warning_items_are_not_a_failure(self) -> None:
        warning = {"type": "item.completed", "item": {"type": "error", "message": "`x` is ignored"}}

        assert backend(FakeRunner(events(warning, ANSWER))).ask("П", "ф").structured is not None

    @pytest.mark.parametrize("output", ["", "not json", events(message("просто текст"))])
    def test_bad_output_is_a_backend_error(self, output: str) -> None:
        with pytest.raises(AgentBackendError):
            backend(FakeRunner(output)).ask("П", "ф")


class TestFailures:
    @pytest.mark.parametrize("reason", [
        "You've hit your usage limit. Upgrade to Pro or try again at 7:40 PM.",
        "stream error: 429 Too Many Requests",
        "unexpected status 503 Service Unavailable",
    ])
    def test_subscription_limit_and_overload_are_model_unavailable(self, reason: str) -> None:
        output = events({"type": "turn.failed", "error": {"message": reason}})

        with pytest.raises(ModelUnavailable, match="codex reported an error"):
            backend(FakeRunner(error=CommandError("exit code 1: …", output=output))).ask("П", "ф")

    def test_other_errors_are_not_model_unavailable(self) -> None:
        output = events({"type": "error", "message": "Not logged in: run codex login"})

        with pytest.raises(AgentBackendError, match="codex login") as raised:
            backend(FakeRunner(error=CommandError("exit code 1", output=output))).ask("П", "ф")
        assert not isinstance(raised.value, ModelUnavailable)

    def test_failed_run_without_events_keeps_the_runner_message(self) -> None:
        with pytest.raises(AgentBackendError, match="No such file"):
            backend(FakeRunner(error=CommandError("[Errno 2] No such file or directory: '/bin/codex'"))).ask("П", "ф")

    def test_process_out_of_time_is_a_timeout(self) -> None:
        with pytest.raises(ModelTimeout):
            backend(FakeRunner(error=CommandTimeout("no answer in 90 s"))).ask("П", "ф")


class TestHelpers:
    def test_strict_schema_requires_every_field_of_every_object(self) -> None:
        schema = {"type": "object", "properties": {"a": {"type": "string"}, "b": {"type": "object", "properties": {"c": {"type": "integer"}}}}}

        strict = strict_schema(schema)

        assert strict["required"] == ["a", "b"] and strict["additionalProperties"] is False
        assert strict["properties"]["b"]["required"] == ["c"] and "required" not in schema

    def test_toml_values_are_quoted_safely(self) -> None:
        assert toml_value('строка "с кавычками"\nи переносом') == '"строка \\"с кавычками\\"\\nи переносом"'
        assert toml_value({"KEY": "v"}) == '{"KEY" = "v"}' and toml_value(["a", "b"]) == '["a", "b"]'
