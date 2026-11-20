"""Памятка и предложенные к ней дополнения."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime


@dataclass(frozen=True, slots=True)
class Suggestion:
    """Дополнение, которое предложила модель. В памятку попадает только после «Принять» человека.

    `replaces` — строка памятки дословно: тогда `text` встаёт на её место, а пустой `text` её убирает. Без него `text`
    дописывается в конец. Владелец 11.11.2026: неверная строка перекрывалась новой припиской вместо замены.
    """

    id: str
    text: str
    reason: str              # почему: что на деле оказалось не так, как в памятке, или чего в ней не было
    created: datetime
    replaces: str = ""


@dataclass(frozen=True, slots=True)
class Playbook:
    id: str
    title: str               # что за дело: «Пройти тест в Moodle»
    site: str                # где: сайт без «www.» или пусто, если памятка не про сайт
    text: str                # как: по шагам. Пусто — памятку предложила модель, а человек её ещё не принял
    created: datetime
    used: datetime | None = None
    suggestions: tuple[Suggestion, ...] = ()

    @property
    def accepted(self) -> bool:
        """Модель видит и читает только принятые памятки."""
        return bool(self.text)

    def with_suggestion(self, suggestion: Suggestion) -> Playbook:
        return replace(self, suggestions=(*self.suggestions, suggestion))

    def without(self, suggestion_id: str) -> Playbook:
        return replace(self, suggestions=tuple(other for other in self.suggestions if other.id != suggestion_id))
