"""Ручка `last_reply`: полный текст прошлого ответа о личной переписке — для «отправь», «нет», «другой вариант»."""

from __future__ import annotations

from typing import ClassVar

from jericho.core.journal.reply_vault import ReplyVault
from jericho.core.tools.description import ToolDescription
from jericho.core.tools.request import ToolRequest
from jericho.core.tools.result import ToolRefusal, ToolResult
from jericho.core.tools.risk import Risk
from jericho.core.tools.tool import Tool


class LastReply(Tool[ToolRequest]):
    """В памяти разговора ответ о переписке — пометкой («прочитал чат…»): пересказ не должен уйти запасной модели.
    Эта ручка — личная (`private`): доверенная модель получает полный текст, недоверенной политика откажет сама.
    Так следующая фраза («отправь», «нет, не Маша») знает, что именно ты предлагал (журнал 24.10.2026).
    """

    name = "last_reply"
    risk = Risk.READ
    service = True
    private: ClassVar[tuple[str, ...]] = ("text",)
    request_type = ToolRequest
    description = ToolDescription(
        when=(
            "в недавнем разговоре твой ответ — пометка о переписке («прочитал чат…», «спросил, отправить ли…»), а "
            "пользователь отвечает на него: «отправь», «да», «нет», «другой вариант», выбор кнопки."
        ),
        does="возвращает полный текст твоего прошлого ответа о личной переписке (пока жив сеанс).",
        returns='{"ok": true, "text": полный текст ответа}.',
        refusals="no_reply — сохранённого ответа нет: спроси пользователя, что он имеет в виду.",
    )

    def __init__(self, vault: ReplyVault) -> None:
        self._vault = vault

    def _run(self, request: ToolRequest) -> ToolResult:
        found = self._vault.latest()
        if found is None:
            raise ToolRefusal("no_reply")
        message, body = found
        return ToolResult.success(text=f"{message}\n\n{body}".strip(), memo="вспомнил свой прошлый ответ о переписке")
