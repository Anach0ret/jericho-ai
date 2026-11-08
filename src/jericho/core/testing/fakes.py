"""Подмены для тестов: подтверждение, модель, сборщик промпта."""

from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jericho.core.agent.context import PendingQuestion
from jericho.core.agent.entities import BackendAnswer
from jericho.core.agent.protocols import AgentBackendError
from jericho.core.prompting.builder import PromptBuilder
from jericho.core.prompting.entities import Skill
from jericho.core.prompting.protocols import PromptContext
from jericho.core.services.confirmation import ConfirmationGate, PendingConfirmation
from jericho.core.services.core_services import CoreServices
from jericho.core.services.paths import Paths
from jericho.core.services.runner import DryRunRunner, SubprocessRunner
from jericho.core.tools.confirm import Confirm
from jericho.core.tools.dispatcher import ToolDispatcher
from jericho.core.tools.middleware import Journal, Refusals
from jericho.core.tools.request import ToolRequest
from jericho.core.tools.result import ToolResult
from jericho.core.tools.session import CallSession
from jericho.core.tools.tool import Tool

NOON = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)


class Source:
    def core(self) -> str:
        return "ЯДРО\n{{skills_index}}\nРАЗГОВОР\n{{recent_exchanges}}\n{{pending_confirmation}}"

    def skill(self, name: str) -> Skill:
        return Skill(name, "рабочий стол", ("open_project", "open_app"), "НАВЫК\n{{projects}}\n{{apps}}")


class Confirmations:
    def __init__(self, pending: PendingConfirmation | None = None) -> None:
        self._pending = pending

    def pending(self) -> PendingConfirmation | None:
        return self._pending

    def ask(self, tool: str, arguments: Mapping[str, object], summary: str, asked_by: str, subject: object = None) -> None:
        self._pending = PendingConfirmation(tool, dict(arguments), summary, NOON, asked_by, subject)

    def take(self) -> PendingConfirmation | None:
        taken, self._pending = self._pending, None
        return taken

    def approve(self, run_id: str) -> PendingConfirmation | None:
        if self._pending is not None:
            self._pending = replace(self._pending, approved_by=run_id)
        return self._pending

    def take_expired(self) -> PendingConfirmation | None:
        return None          # в подмене вопрос не стареет: срок проверяют тесты файлового хранилища

    def mark_reminded(self) -> PendingConfirmation | None:
        if self._pending is not None:
            self._pending = replace(self._pending, reminded=True)
        return self._pending


def builder(confirmations: Confirmations | None = None, contexts: Sequence[PromptContext] = ()) -> PromptBuilder:
    """Сборщик промпта с подставными текстами: ядро, один навык в списке и разговор."""
    return PromptBuilder(Source(), (PendingQuestion(confirmations or Confirmations()), *contexts), ["desktop"])


class FakeBackend:
    def __init__(
        self, structured: dict[str, object] | None = None, error: str = "", error_type: type[AgentBackendError] = AgentBackendError
    ) -> None:
        self.asked: list[tuple[str, str]] = []
        self._structured = structured
        self._error = error
        self._error_type = error_type

    def ask(self, system_prompt: str, phrase: str) -> BackendAnswer:
        self.asked.append((system_prompt, phrase))
        if self._error:
            raise self._error_type(self._error)
        return BackendAnswer(self._structured, {"num_turns": 3})


def execute(tool: Tool[Any], request: ToolRequest | Mapping[str, object]) -> ToolResult:
    """Вызов **самой ручки** в тесте: проверка параметров, слои журнала и отказов — отказ приходит ответом.

    Политики риска, проверки «навык загружен» и срока здесь нет: это проверка ручки, а не того, пропустит ли её
    каркас. Политику каркас проверяет сам (`tests/core/test_risk_policy.py`). Готовый запрос — когда параметры
    верные; словарь — чтобы проверить, как ручка отвечает на неверные.
    """
    arguments = request.model_dump(exclude_unset=True) if isinstance(request, ToolRequest) else request
    return ToolDispatcher([Journal, Refusals]).call(tool, arguments)


def say_yes(gate: ConfirmationGate, *tools: Tool[Any]) -> ToolResult:
    """«Да» пользователя в следующей фразе: вызов ручки ядра `confirm()` так, как его сделает модель.

    `gate` — служба подтверждения этой, новой фразы; ручки должны быть собраны с ней же. Сначала «да» слышит
    вход поручения (как `PhraseConsent` в работе), потом модель зовёт `confirm()`.
    """
    gate.user_said_yes()
    dispatcher = ToolDispatcher([Journal, Refusals])
    return dispatcher.call(Confirm(gate, dispatcher, tools, CallSession()), {})


def fake_core(state: Path, dry_run: bool = True) -> CoreServices:
    """Службы ядра для теста навыка: папки — во временной `state`, «вхолостую» — внешние команды только в журнал.

    Нужны, чтобы собрать навык (`skill.ready(...)`) — ручки обычно собираются там — и прогнать проверки структуры.
    """
    return CoreServices(
        DryRunRunner(SubprocessRunner()) if dry_run else SubprocessRunner(), ConfirmationGate(Confirmations(), "test"),
        Paths(state / "state", state / "run"), dry_run=dry_run,
    )
