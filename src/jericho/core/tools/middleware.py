"""Слои, которые есть у каждого вызова ручки. Порядок задаёт `TOOL_MIDDLEWARE` в настройках проекта."""

from __future__ import annotations

import logging
import time

from jericho.core.errors import PortError
from jericho.core.tools.dispatcher import CallHandler, ToolCall
from jericho.core.tools.private import PrivateFields
from jericho.core.tools.result import ToolRefusal, ToolResult

logger = logging.getLogger(__name__)


class Journal:
    """Записывает каждый вызов: ручка, параметры, итог и время. Ставится снаружи — видит уже готовый ответ.

    Длинный текст в ответе (руководство навыка) в журнал целиком не идёт: там важно, что его отдали, а не он сам.
    Личные поля ручки (`Tool.private`) не идут вовсе: вместо них — «скрыто: …», а у записи — `private: true`,
    по ней разговор и чтение журнала узнают, что в этой фразе была чужая переписка.
    """

    TEXT_LIMIT = 300

    def __init__(self, handle: CallHandler) -> None:
        self._handle = handle

    def __call__(self, call: ToolCall) -> ToolResult:
        started = time.perf_counter()
        result = self._handle(call)
        params, answer = PrivateFields(call.tool.private), PrivateFields(call.tool.private_in(result))
        logger.info("tool", extra={"data": {
            "tool": call.tool.name,
            "params": params.mask(call.arguments),
            "result": {name: self._short(value) for name, value in answer.mask(result.to_dict()).items()},
            "ms": round((time.perf_counter() - started) * 1000, 1),
            **({"private": True} if params or answer else {}),
        }})
        return result

    def _short(self, value: object) -> object:
        if isinstance(value, str) and len(value) > self.TEXT_LIMIT:
            return f"{value[: self.TEXT_LIMIT]}… (всего {len(value)} знаков)"
        if isinstance(value, dict):
            return {name: self._short(item) for name, item in value.items()}
        return value


class Refusals:
    """Отказ ручки, неверные параметры и ошибку внешнего мира превращает в ответ с кодом — не в исключение."""

    def __init__(self, handle: CallHandler) -> None:
        self._handle = handle

    def __call__(self, call: ToolCall) -> ToolResult:
        try:
            return self._handle(call)
        except ToolRefusal as refusal:
            return ToolResult.failure(refusal.code, **refusal.details)
        except PortError as error:
            return ToolResult.failure(error.code, detail=str(error))
