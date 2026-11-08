"""Подмена для тестов: память разговора в списке."""

from __future__ import annotations

from collections.abc import Sequence

from jericho.core.agent.entities import AgentReply
from jericho.core.testing import NOON
from jericho.modules.dialogue.entities import Exchange


class Memory:
    """Помнит всё, что ей дали, без срока давности."""

    def __init__(self, exchanges: Sequence[Exchange] = ()) -> None:
        self.exchanges = list(exchanges)

    def recent(self) -> tuple[Exchange, ...]:
        return tuple(self.exchanges)

    def remember(self, phrase: str, reply: AgentReply, foreign: Sequence[str] = ()) -> None:
        self.exchanges.append(Exchange.of(NOON, phrase, reply, tuple(foreign)))
