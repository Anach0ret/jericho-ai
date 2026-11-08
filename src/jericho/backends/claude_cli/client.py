"""Бэкенд модели: программа `claude` в режиме одного запроса (`claude -p`), по подписке.

Цикл «модель → инструмент → модель» ведёт сама программа: она запускает наш MCP-сервер,
передаёт модели его инструменты и исполняет её вызовы, пока модель не даст итоговый ответ.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path

from jericho.core.agent.entities import BackendAnswer
from jericho.core.agent.protocols import AgentBackendError, ModelTimeout, ModelUnavailable
from jericho.core.services.phrase_deadline import PhraseDeadline
from jericho.core.services.runner import CommandError, CommandRunner, CommandTimeout


class ClaudeCliBackend:
    """Запускает `claude -p` с нашим промптом, одним MCP-сервером и обязательной формой ответа."""

    MCP_SERVER = "jericho"
    _META_KEYS = ("duration_ms", "duration_api_ms", "num_turns", "total_cost_usd")
    # Как `claude` говорит о лимите подписки и перегрузке: «Claude AI usage limit reached», «You've hit your session
    # limit · resets 5pm», «rate_limit_error», «overloaded_error», код ошибки API 429 или 5xx.
    _UNAVAILABLE = re.compile(
        r"usage limit|hit your \w*\s*limit|rate.?limit|overloaded|api_error_status'?\"?:\s*(429|5\d\d)", re.IGNORECASE
    )

    def __init__(
        self,
        runner: CommandRunner,
        executable: Path,
        model: str,
        mcp_command: Sequence[str],
        tools: Sequence[str],
        reply_schema: Mapping[str, object],
        mcp_environment: Mapping[str, str] | None = None,
        deadline: PhraseDeadline | None = None,
        builtin_tools: Sequence[str] = (),
    ) -> None:
        self._runner = runner
        self._executable = str(executable)
        self._model = model
        self._mcp_command = list(mcp_command)
        self._tools = tuple(tools)
        self._reply_schema = reply_schema
        self._builtin_tools = tuple(builtin_tools)    # встроенные инструменты claude, разрешённые поимённо
        self._mcp_environment = dict(mcp_environment or {})   # что наш сервер должен унаследовать от этого запуска
        self._deadline = deadline or PhraseDeadline()         # срок фразы идёт к серверу ручек: после него ручки не начнутся

    def ask(self, system_prompt: str, phrase: str) -> BackendAnswer:
        try:
            output = self._runner.run(self._command(system_prompt), stdin=phrase)   # фраза — через stdin, не аргументом
        except CommandTimeout as error:
            raise ModelTimeout(str(error)) from error
        except CommandError as error:
            if not error.output:
                raise self._failure("", str(error)) from error
            output = error.output     # ошибку `claude` завершает кодом 1, а причину пишет тем же JSON — разбираем его
        try:
            result = json.loads(output)
        except ValueError as error:
            raise AgentBackendError(f"claude answered not with JSON: {output[:200]}") from error
        if not isinstance(result, dict):
            raise self._failure("claude reported an error: ", str(result))
        if result.get("is_error") or result.get("subtype", "success") != "success":
            # Причина — вперёд: за счётчиками токенов она не влезала в журнал (журнал 29.10.2026).
            raise self._failure(f"claude reported an error: {result.get('subtype')}: {result.get('result')} | ", str(result))
        meta = {key: result[key] for key in self._META_KEYS if key in result}
        meta["models"] = list(result.get("modelUsage", {}))
        return BackendAnswer(structured=result.get("structured_output"), meta=meta)

    def _failure(self, prefix: str, text: str) -> AgentBackendError:
        """Лимит подписки и перегрузка — `ModelUnavailable`: поручение может взять запасной бэкенд. Ищется по всему
        тексту — до обрезки: в ответе `claude` поле `result` с причиной стоит далеко от начала."""
        kind = ModelUnavailable if self._UNAVAILABLE.search(prefix + text) else AgentBackendError
        return kind(f"{prefix}{text[:300]}")

    def _environment(self) -> dict[str, str]:
        """Окружение сервера ручек — на этот запуск: срок фразы свой у каждой."""
        return {**self._mcp_environment, **self._deadline.environment()}

    def _command(self, system_prompt: str) -> list[str]:
        server = {"command": self._mcp_command[0], "args": self._mcp_command[1:], "env": self._environment()}
        mcp_config = {"mcpServers": {self.MCP_SERVER: server}}
        return [
            self._executable, "-p",
            "--system-prompt", system_prompt,
            "--model", self._model,
            "--tools", ",".join(self._builtin_tools),        # встроенные (shell, файлы, веб) — только названные; обычно ни одного
            "--mcp-config", json.dumps(mcp_config),
            "--strict-mcp-config",                           # только наш сервер, чужие MCP не подхватываются
            "--allowedTools", *self._builtin_tools, *(f"mcp__{self.MCP_SERVER}__{tool}" for tool in self._tools),
            "--setting-sources", "",                         # без личных настроек, памяти и CLAUDE.md
            "--no-session-persistence",
            "--output-format", "json",
            "--json-schema", json.dumps(self._reply_schema),
        ]
