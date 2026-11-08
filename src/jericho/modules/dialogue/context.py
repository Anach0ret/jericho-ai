"""Недавний разговор в общем промпте."""

from __future__ import annotations

from jericho.modules.dialogue.protocols import ConversationMemory


class RecentExchanges:
    """Подстановка `{{recent_exchanges}}` для раздела модуля."""

    def __init__(self, memory: ConversationMemory) -> None:
        self._memory = memory

    def values(self) -> dict[str, str]:
        exchanges = self._memory.recent()
        if not exchanges:
            return {"recent_exchanges": "Недавних реплик нет — фраза начинает новый разговор."}
        return {"recent_exchanges": "\n".join(
            f"- пользователь: «{exchange.phrase}» → ты ({exchange.status.value}): «{exchange.said}»"
            for exchange in exchanges
        )}
