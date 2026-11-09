"""Вызов ручки через цепочку слоёв — как запрос в Django проходит через middleware к view."""

from __future__ import annotations

import logging
import sys
import traceback
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from jericho.core.services.phrase_deadline import PhraseDeadline
from jericho.core.tools.deadline import Deadline, ToolTimeout
from jericho.core.tools.private import PrivateFields
from jericho.core.tools.request import ToolRequest
from jericho.core.tools.result import ToolRefusal, ToolResult
from jericho.core.tools.session import CallSession
from jericho.core.tools.tool import Tool

if TYPE_CHECKING:   # политика знает о вызове, поэтому вызов знает о ней только по имени типа
    from jericho.core.tools.policy import RiskPolicy

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ToolCall:
    """Один вызов: какая ручка и с какими параметрами, как их прислала модель. Это то, что видит каждый слой."""

    tool: Tool[Any]
    arguments: Mapping[str, object]
    session: CallSession     # что уже произошло в этой фразе: какие навыки загружены


type CallHandler = Callable[[ToolCall], ToolResult]
"""Тот, кто доводит вызов до результата: следующий слой или сама ручка."""

type ToolMiddleware = Callable[[CallHandler], CallHandler]
"""Слой: получает следующего в цепочке и возвращает обёртку над ним. Обычно это класс с `__init__` и `__call__`."""


class ToolDispatcher:
    """Проводит вызов ручки через слои. Первый в списке — самый внешний: видит вызов первым, а результат последним.

    В самой середине параметры проверяются по запросу ручки: до `_run` доходит только то, что прошло проверку.

    После проверки параметров и до ручки — политика риска (`core/tools/policy.py`): её, в отличие от слоёв,
    настройками не убрать. Диспетчер без политики — только для вызова ручки руками из терминала: там человек
    сам набирает команду, и это и есть его согласие.

    Снаружи всех слоёв — обработчик неожиданных исключений. Он не входит в настраиваемый список: что бы ни
    упало в ручке или в слое, вызов оставляет запись в журнале, а модель получает короткий код сбоя.
    Там же срок вызова: ручка, которая в него не уложилась, обрывается. И срок всей фразы (`PhraseDeadline`): вышел —
    ручка не начинается, кто бы её ни звал — цикл по ключу, сервер ручек CLI-бэкенда или `confirm` (ревью 02.11.2026,
    сводка №9; критика плана 07.11.2026).
    """

    INVALID_PARAMETERS = "invalid_parameters"
    TOOL_FAILED = "tool_failed"
    TOOL_TIMEOUT = "tool_timeout"
    PHRASE_DEADLINE_PASSED = "phrase_deadline_passed"

    def __init__(
        self,
        middleware: Sequence[ToolMiddleware] = (),
        session: CallSession | None = None,
        deadline: Deadline | None = None,
        policy: RiskPolicy | None = None,
        phrase: PhraseDeadline | None = None,
    ) -> None:
        self._session = session or CallSession()
        self._phrase = phrase or PhraseDeadline()
        self._policy = policy
        self._deadline = deadline or Deadline()
        handler: CallHandler = self._run
        for layer in reversed(middleware):
            handler = layer(handler)
        self._handler = handler

    @property
    def session(self) -> CallSession:
        return self._session

    def call(self, tool: Tool[Any], arguments: Mapping[str, object], budget: float | None = None) -> ToolResult:
        """`budget` — сколько секунд осталось у поручения; срок ручки не выходит ни за него, ни за срок фразы."""
        left = self._phrase.left()
        budget = left if budget is None else budget if left is None else min(budget, left)
        if budget is not None and budget <= 0:
            detail = "срок поручения вышел — ничего не начато; скажи, что не успел"
            result = ToolResult.failure(self.PHRASE_DEADLINE_PASSED, detail=detail)
            logger.warning("tool", extra={"data": {"tool": tool.name, "result": result.to_dict()}})
            return result
        try:
            with self._deadline.limit(budget):
                return self._handler(ToolCall(tool, arguments, self._session))
        except ToolTimeout:
            # Что успело произойти до обрыва, неизвестно: модель должна сказать об этом, а не повторять вызов.
            detail = "не уложился в срок; что успело произойти, неизвестно — не повторяй, скажи об этом"
            failed = ToolResult.failure(self.TOOL_TIMEOUT, seconds=self._deadline.seconds, detail=detail)
            self._journal_failure(tool, arguments, failed)
            return failed
        except Exception as error:
            # Текст исключения модели не отдаём: в нём может оказаться что угодно. Подробности — в журнале.
            failed = ToolResult.failure(self.TOOL_FAILED, detail=type(error).__name__)
            self._journal_failure(tool, arguments, failed)
            return failed

    @staticmethod
    def _journal_failure(tool: Tool[Any], arguments: Mapping[str, object], result: ToolResult) -> None:
        """Запись о вызове, который оборвался мимо слоёв; вызывается из `except` — трассировка попадает в журнал.

        Личные поля скрыты, как у слоя журнала. У ручки с личными полями — и текст исключения: в нём мог оказаться
        сам текст (`ValueError(f"… {message}")`), поэтому в журнал идут только вид ошибки и строки кода (ревью П1 №1).
        """
        data = {"tool": tool.name, "params": PrivateFields(tool.private).mask(arguments), "result": result.to_dict()}
        if not tool.private:
            logger.exception("tool", extra={"data": data})
            return
        error = sys.exc_info()[1]
        trace = "".join(traceback.format_tb(error.__traceback__)) if error is not None else ""
        logger.error("tool", extra={"data": {**data, "private": True, "error": type(error).__name__, "trace": trace}})

    def _run(self, call: ToolCall) -> ToolResult:
        request = self._request(call)
        if self._policy is not None:
            self._policy.admit(call)
        result = call.tool.execute(request)
        if call.tool.private and result.ok:
            call.session.read_private()
        if call.tool.local and result.ok:
            call.session.read_local()
        return result

    def _request(self, call: ToolCall) -> ToolRequest:
        """Параметры от модели → проверенный запрос. Не прошли проверку — отказ со списком «поле — что не так»."""
        try:
            return call.tool.request_type.model_validate(dict(call.arguments))
        except ValidationError as error:
            problems = [
                {"field": ".".join(str(part) for part in problem["loc"]), "problem": problem["msg"]}
                for problem in error.errors()
            ]
            raise ToolRefusal(self.INVALID_PARAMETERS, problems=problems) from None
