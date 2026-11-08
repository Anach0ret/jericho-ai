"""Личные поля ручки (`Tool.private`) вне ответа модели: одно правило для журнала, аварийной записи и вопроса «да»."""

from __future__ import annotations

from collections.abc import Iterable, Mapping


class PrivateFields:
    """Вместо значения личного поля — «скрыто: N знаков»: видно, что текст был, но не сам текст.

    Раньше скрывал только слой журнала, а аварийная запись диспетчера, вопрос «да» каркаса и запись `confirm` несли
    поля открыто (ревью 02.11.2026, П1 №1, П2 №2). Теперь все они идут через этот класс.
    """

    def __init__(self, names: Iterable[str]) -> None:
        self._names = frozenset(names)

    def __bool__(self) -> bool:
        return bool(self._names)

    def mask(self, values: Mapping[str, object]) -> dict[str, object]:
        return {name: self.hidden(value) if name in self._names else value for name, value in values.items()}

    @staticmethod
    def hidden(value: object) -> str:
        """Сколько было, но не что: по этому видно, что ручка отдала текст, а сам текст в журнале не лежит."""
        if isinstance(value, str):
            return f"скрыто: {len(value)} знаков"
        if isinstance(value, list | tuple | dict):
            return f"скрыто: {len(value)} шт."
        return "скрыто"
