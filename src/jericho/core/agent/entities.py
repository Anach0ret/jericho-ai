"""Разговор с моделью: что ей отправляем и что получаем обратно."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum


class ReplyStatus(StrEnum):
    DONE = "done"            # сделано
    CLARIFY = "clarify"      # нужен ответ пользователя
    REFUSED = "refused"      # не будет сделано, с причиной
    IGNORED = "ignored"      # фраза — не команда
    FAILED = "failed"        # сбой самого Jericho: модель недоступна или ответила не по форме
    STOPPED = "stopped"      # остановлено пользователем (`stop`); модель такого статуса не даёт


@dataclass(frozen=True, slots=True)
class AgentReply:
    """Итог поручения: строка, которую видно сразу, и, если форма ответа его предусматривает, подробный текст."""

    status: ReplyStatus
    message: str = ""
    body: str = ""       # подробности — у формы «отчёт»; у короткой формы пусто
    private: bool = False    # в ответе может быть пересказ личной переписки: показать — да, хранить — нет
    options: tuple[str, ...] = ()   # варианты ответа на вопрос (clarify): кнопки в уведомлении и в окне


@dataclass(frozen=True, slots=True)
class BackendAnswer:
    """Что вернул бэкенд модели: разобранный ответ и служебные сведения (время, число ходов, цена)."""

    structured: Mapping[str, object] | None
    meta: Mapping[str, object] = field(default_factory=dict)
