"""Описание инструмента для модели — из четырёх обязательных частей."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ToolDescription:
    """Что модель читает об инструменте. Порядок частей задан здесь, а не в каждом инструменте.

    «Когда» идёт первым: по нему модель решает, вызывать ли инструмент вообще.
    """

    when: str         # в каких просьбах пользователя инструмент нужен
    does: str         # что он сделает и чего не сделает
    returns: str      # ответ при успехе и как читать его поля
    refusals: str     # коды отказов и что делать с теми, что требуют реакции

    def render(self) -> str:
        return "\n".join((
            f"Когда: {self.when}",
            f"Что делает: {self.does}",
            f"Вернёт: {self.returns}",
            f'Отказы {{"ok": false, "error": код}}: {self.refusals}',
        ))
