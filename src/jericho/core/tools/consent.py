"""Ручке нужно «да»: спросить службу подтверждения и, если согласия ещё нет, отказать с вопросом."""

from __future__ import annotations

from collections.abc import Mapping

from jericho.core.services.confirmation import ConfirmationGate
from jericho.core.tools.result import ToolRefusal

NEEDS_CONFIRM = "needs_confirm"


def require_consent(
    gate: ConfirmationGate, tool: str, arguments: Mapping[str, object], summary: str, subject: object = None, **details: object
) -> None:
    """«Да» из следующей фразы на этот вызов (и `subject`); нет его — отказ `needs_confirm`, вопрос уже записан.

    В отказе — `summary` (что сказать пользователю), подробности ручки и пометки службы: рядом никого, всё
    изменилось с прошлого вопроса, прежний вопрос снят.
    """
    consent = gate.consent(tool, arguments, summary, subject)
    if not consent.granted:
        raise ToolRefusal(NEEDS_CONFIRM, summary=summary, **details, **consent.notes())
