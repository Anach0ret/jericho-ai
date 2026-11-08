"""Бэкенд без модели: вызывает ручки и отвечает по сценарию."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from jericho.backends.scripted.script import Step
from jericho.core.agent.entities import BackendAnswer
from jericho.core.tools.dispatcher import ToolDispatcher
from jericho.core.tools.tool import Tool


class ScriptedBackend:
    """Ведёт себя как модель, чьи решения известны заранее.

    Ручки вызываются по-настоящему, через тот же диспетчер и те же слои, что и от модели: отказ, подтверждение,
    журнал. Поэтому на сценарии видно, как ассистент собран, — без ключа, без сети и без расхода подписки.
    Чего сценарий не покажет — выбора модели: его проверяют прогоном фраз на настоящем бэкенде.
    """

    NO_SCRIPT = "Бэкенд «сценарий»: модели нет, а в сценарии нет записи на это поручение"

    def __init__(
        self,
        steps: Sequence[Step],
        tools: Sequence[Tool[Any]],
        dispatcher: ToolDispatcher,
        reply_schema: Mapping[str, object],
    ) -> None:
        self._steps = tuple(steps)
        self._tools = {tool.name: tool for tool in tools}
        self._dispatcher = dispatcher
        self._reply_schema = reply_schema

    def ask(self, system_prompt: str, phrase: str) -> BackendAnswer:
        step = next((step for step in self._steps if step.fits(phrase)), None)
        if step is None:
            return BackendAnswer(self._refusal(), {"scripted": True, "num_turns": 1})
        made = [self._call(call.tool, call.arguments) for call in step.calls]
        return BackendAnswer(step.reply, {"scripted": True, "num_turns": len(made) + 1, "calls": made})

    def _call(self, name: str, arguments: Mapping[str, object]) -> dict[str, object]:
        tool = self._tools.get(name)
        if tool is None:
            return {"tool": name, "error": "unknown_tool"}
        result = self._dispatcher.call(tool, arguments)
        return {"tool": name, "ok": True} if result.ok else {"tool": name, "error": result.error}

    def _refusal(self) -> dict[str, object]:
        """Ответ «записи нет» в той форме, которую выбрал проект: строка идёт в первое текстовое поле формы."""
        properties = self._reply_schema.get("properties")
        # Только строковые поля формы: первое — причина, остальные — пусто. Необязательные списки (варианты кнопок) — нет.
        text_fields = [
            name for name, spec in properties.items() if name != "status" and isinstance(spec, Mapping) and spec.get("type") == "string"
        ] if isinstance(properties, Mapping) else ["message"]
        return {"status": "refused", **{name: (self.NO_SCRIPT if name == text_fields[0] else "") for name in text_fields}}
