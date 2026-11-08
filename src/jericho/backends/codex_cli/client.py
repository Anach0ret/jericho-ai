"""Бэкенд модели: программа `codex` в режиме одного запроса (`codex exec`), по подписке ChatGPT.

Как и у `claude_cli`, цикл «модель → инструмент → модель» ведёт сама программа: она запускает наш MCP-сервер, модель
вызывает ручки (в этой версии codex — из кода в `exec`, где кроме ручек ничего нет) и отвечает по схеме.

Изоляция от личной настройки codex — в самой команде: `--ignore-user-config` (без своих MCP, плагинов и роли из
config.toml), `--ephemeral` (сессия не сохраняется), пустая временная папка как рабочая, песочница только на чтение.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from jericho.core.agent.entities import BackendAnswer
from jericho.core.agent.protocols import AgentBackendError, ModelTimeout, ModelUnavailable
from jericho.core.services.phrase_deadline import PhraseDeadline
from jericho.core.services.runner import CommandError, CommandRunner, CommandTimeout


def strict_schema(schema: Mapping[str, Any]) -> dict[str, Any]:
    """Схема ответа для строгого режима OpenAI: у каждого объекта обязательны все поля и нет лишних.

    Необязательное поле становится обязательным: модель отдаёт его пустым («options»: []). Иначе codex отказывает:
    «'required' is required to include every key in properties» (проба 02.11.2026).
    """
    result: dict[str, Any] = {key: _strict(value) for key, value in schema.items()}
    if result.get("type") == "object" and isinstance(result.get("properties"), dict):
        result["required"] = list(result["properties"])
        result["additionalProperties"] = False
    return result


def _strict(value: Any) -> Any:
    if isinstance(value, Mapping):
        return strict_schema(value)
    if isinstance(value, list):
        return [_strict(item) for item in value]
    return value


def toml_value(value: object) -> str:
    """Значение для `-c ключ=значение`: codex читает его как TOML; строка в JSON-записи — верная строка TOML."""
    if isinstance(value, Mapping):
        return "{" + ", ".join(f"{json.dumps(str(key))} = {toml_value(item)}" for key, item in value.items()) + "}"
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(toml_value(item) for item in value) + "]"
    return json.dumps(value, ensure_ascii=False)


class CodexCliBackend:
    """Запускает `codex exec` с нашим промптом, одним MCP-сервером и обязательной формой ответа; фраза — через stdin."""

    MCP_SERVER = "jericho"
    SCHEMA_FILE = "reply-schema.json"
    # Как codex и API говорят о лимите подписки и перегрузке: «You've hit your usage limit», «rate limit», 429, 5xx.
    _UNAVAILABLE = re.compile(
        r"usage limit|hit your \w*\s*limit|rate.?limit|quota|overloaded|too many requests|\b(429|50[0-4])\b", re.IGNORECASE
    )

    def __init__(
        self,
        runner: CommandRunner,
        executable: Path,
        model: str,
        reasoning_effort: str,
        mcp_command: Sequence[str],
        tools: Sequence[str],
        reply_schema: Mapping[str, object],
        mcp_environment: Mapping[str, str] | None = None,
        deadline: PhraseDeadline | None = None,
        disabled_features: Sequence[str] = (),
        tool_timeout: float = 60.0,
        inherited: Mapping[str, str] = os.environ,
    ) -> None:
        self._runner = runner
        self._executable = str(executable)
        self._model = model
        self._reasoning_effort = reasoning_effort
        self._mcp_command = list(mcp_command)
        self._tools = tuple(tools)
        self._reply_schema = strict_schema(reply_schema)
        self._mcp_environment = dict(mcp_environment or {})   # что наш сервер должен унаследовать от этого запуска
        self._deadline = deadline or PhraseDeadline()         # срок фразы идёт к серверу ручек: после него ручки не начнутся
        self._disabled_features = tuple(disabled_features)
        self._tool_timeout = tool_timeout
        self._inherited = inherited     # окружение этого процесса: его имена сервер ручек получает, как у `claude`

    def ask(self, system_prompt: str, phrase: str) -> BackendAnswer:
        with TemporaryDirectory(prefix="jericho-codex-") as folder:
            schema = Path(folder) / self.SCHEMA_FILE
            schema.write_text(json.dumps(self._reply_schema), encoding="utf-8")
            try:
                output = self._runner.run(self._command(system_prompt, Path(folder), schema), stdin=phrase)
            except CommandTimeout as error:
                raise ModelTimeout(str(error)) from error
            except CommandError as error:
                raise self._failure(self._events(error.output), str(error)) from error
        return self._answer(self._events(output))

    def _answer(self, events: list[dict[str, Any]]) -> BackendAnswer:
        problem = self._problem(events)
        if problem:
            raise self._failure(events, problem)
        messages = [item["text"] for item in self._items(events, "agent_message") if isinstance(item.get("text"), str)]
        if not messages:
            raise AgentBackendError("codex gave no answer")
        try:
            structured = json.loads(messages[-1])
        except ValueError as error:
            raise AgentBackendError(f"codex answered not with JSON: {messages[-1][:200]}") from error
        return BackendAnswer(structured=structured if isinstance(structured, dict) else None, meta=self._meta(events))

    def _meta(self, events: list[dict[str, Any]]) -> dict[str, object]:
        usage: dict[str, Any] = {}
        for event in events:
            if event.get("type") == "turn.completed" and isinstance(event.get("usage"), dict):
                usage = event["usage"]
        return {
            "models": [self._model],
            "num_turns": len(self._items(events, "mcp_tool_call")) + 1,
            "input_tokens": usage.get("input_tokens", 0),
            "cached_tokens": usage.get("cached_input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
        }

    @staticmethod
    def _events(output: str) -> list[dict[str, Any]]:
        """Вывод `--json` — по событию на строку; посторонние строки пропускаются."""
        events: list[dict[str, Any]] = []
        for line in output.splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict):
                events.append(event)
        return events

    @staticmethod
    def _items(events: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
        return [
            event["item"] for event in events
            if event.get("type") == "item.completed" and isinstance(event.get("item"), dict) and event["item"].get("type") == kind
        ]

    @staticmethod
    def _problem(events: list[dict[str, Any]]) -> str:
        """Ошибка хода: `turn.failed` или `error`. Предупреждения о настройках (`item` типа error) — не ошибка хода."""
        for event in events:
            if event.get("type") == "turn.failed":
                error = event.get("error")
                return str(error.get("message") if isinstance(error, dict) else error)
            if event.get("type") == "error":
                return str(event.get("message", event))
        return ""

    def _failure(self, events: list[dict[str, Any]], text: str) -> AgentBackendError:
        """Лимит подписки и перегрузка — `ModelUnavailable`: поручение может взять запасной бэкенд."""
        reason = self._problem(events) or text
        kind = ModelUnavailable if self._UNAVAILABLE.search(reason) else AgentBackendError
        return kind(f"codex reported an error: {reason[:300]}")

    def _command(self, system_prompt: str, folder: Path, schema: Path) -> list[str]:
        environment = {**self._mcp_environment, **self._deadline.environment()}     # срок фразы свой у каждой
        server = f"mcp_servers.{self.MCP_SERVER}"
        return [
            self._executable, "exec", "--json",
            "--ignore-user-config", "--ignore-rules",        # без личного config.toml (свои MCP, плагины, роль) и правил
            "--ephemeral", "--skip-git-repo-check",
            "--sandbox", "read-only", "-c", 'approval_policy="never"',     # запись и выход наружу — отказ, не вопрос
            "-c", 'web_search="disabled"',
            *(argument for feature in self._disabled_features for argument in ("--disable", feature)),
            "--cd", str(folder),                            # рабочая папка — пустая временная
            "--model", self._model, "-c", f"model_reasoning_effort={toml_value(self._reasoning_effort)}",
            "-c", f"developer_instructions={toml_value(system_prompt)}",
            "-c", f"{server}.command={toml_value(self._mcp_command[0])}",
            "-c", f"{server}.args={toml_value(self._mcp_command[1:])}",
            # Сервер ручек получает окружение этого процесса, как у `claude`: без HYPRLAND_INSTANCE_SIGNATURE, Wayland и
            # D-Bus ручки рабочего стола не видят его (проба 02.11.2026). codex передаёт только названные переменные.
            "-c", f"{server}.env_vars={toml_value(sorted(set(self._inherited) - set(environment)))}",
            "-c", f"{server}.env={toml_value(environment)}",
            "-c", f"{server}.tool_timeout_sec={self._tool_timeout:g}",
            # Одобрение codex — лишнее: согласие на опасное спрашивает Jericho (`needs_confirm`). Без этого codex с
            # approval_policy="never" отклоняет каждую ручку, кроме только читающих (проба 02.11.2026).
            *(argument for tool in self._tools for argument in ("-c", f'{server}.tools.{tool}.approval_mode="approve"')),
            "--output-schema", str(schema),
            "-",                                            # фраза — из stdin, не аргументом
        ]
