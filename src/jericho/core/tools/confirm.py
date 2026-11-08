"""Ручка ядра `confirm`: «да» пользователя на вопрос из прошлой фразы."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from typing import Any

from jericho.core.services.confirmation import ConfirmationGate
from jericho.core.tools.description import ToolDescription
from jericho.core.tools.dispatcher import ToolDispatcher
from jericho.core.tools.request import ToolRequest
from jericho.core.tools.result import ToolRefusal, ToolResult
from jericho.core.tools.risk import Approval, Risk
from jericho.core.tools.session import CallSession
from jericho.core.tools.tool import Tool


class ConfirmRequest(ToolRequest):
    """Параметров нет: что подтверждается, помнит ядро, а не модель."""


class Confirm(Tool[ConfirmRequest]):
    """Выполняет вызов, о котором Jericho спросил в прошлой фразе, — тот самый, с теми же параметрами.

    Вызов идёт через ту же цепочку слоёв, что и обычный. Навык для него загружать не нужно: модель ничего
    не выбирает, решение уже принято пользователем.
    """

    name = "confirm"
    risk = Risk.EFFECT      # выполняет то, на что просили согласие
    approval = Approval.TOOL    # согласие уже дано — это оно и есть; подтверждённая ручка проходит политику сама
    relays = True     # предел пользователя — у подтверждённой ручки: её вызов идёт через тот же диспетчер (П1 №5)
    request_type = ConfirmRequest
    description = ToolDescription(
        when=(
            "в прошлой фразе ты спросил подтверждение (в промпте есть «Ждёт подтверждения»), а пользователь "
            "ответил «да», «подтверждаю», «давай»."
        ),
        does=(
            "выполняет ровно тот вызов, о котором был вопрос. Параметров нет, load_skill не нужен. "
            "На «нет» и на другую команду не вызывай."
        ),
        returns='ответ подтверждённой ручки и "confirmed": её имя.',
        refusals=(
            "no_yes_from_user — пользователь ответил не «да» (ядро проверяет саму фразу): ничего не сделано, спроси заново; "
            "nothing_to_confirm — вопроса не было, он устарел (2 минуты) или задан в этой же фразе. Если ты спрашивал «да» "
            "текстом, не вызвав инструмент, — вызови инструмент действия сейчас: он задаст настоящий вопрос; "
            "needs_confirm + changed — с момента вопроса всё изменилось, ничего не сделано: скажи об этом и спроси заново."
        ),
    )

    def __init__(
        self, gate: ConfirmationGate, dispatcher: ToolDispatcher, tools: Sequence[Tool[Any]], session: CallSession
    ) -> None:
        self._gate = gate
        self._dispatcher = dispatcher
        self._tools = {tool.name: tool for tool in tools}
        self._session = session

    def _run(self, request: ConfirmRequest) -> ToolResult:
        if self._gate.waiting_for_yes():
            raise ToolRefusal(
                "no_yes_from_user",
                detail="пользователь не сказал «да» отдельной фразой — ничего не сделано; спроси ещё раз, нужен ли этот шаг",
            )
        pending = self._gate.grant()
        tool = self._tools.get(pending.tool) if pending is not None else None
        if pending is None or tool is None:
            raise ToolRefusal(
                "nothing_to_confirm",
                detail="сейчас ничего не ждёт подтверждения: вопрос задаёт инструмент действия — вызови его, а не спрашивай «да» сам",
            )
        if tool.skill:
            self._session.load(tool.skill)
        result = self._dispatcher.call(tool, pending.arguments)
        return replace(result, data={**result.data, "confirmed": tool.name})

    def private_in(self, result: ToolResult) -> tuple[str, ...]:
        """Ответ — ответ подтверждённой ручки: и личные поля у него её (ревью 02.11.2026, П2 №2)."""
        tool = self._tools.get(str(result.data.get("confirmed", "")))
        return tool.private_in(result) if tool is not None else ()
