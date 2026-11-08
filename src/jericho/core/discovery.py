"""Части ассистента по именам пакетов из настроек: навыки, модули, службы, бэкенды — как приложения у Django.

Правило у всех одно: в пакете лежит файл с условленным именем (`skill.py`, `module.py`, …), а в нём ровно один
класс-наследник основы. Здесь оно записано один раз; загрузчики частей называют только основу, файл и ошибку.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from importlib import import_module


class PartLoader[PartT]:
    """Находит часть в пакете и собирает её. Пакета, файла или класса нет — ошибка вида `error`, а не трассировка.

    `setting` — откуда пакет назван, для начала сообщения: «agent.backend: …». `required` — атрибуты класса,
    которые наследник обязан объявить.
    """

    def __init__(
        self, base: type[PartT], file: str, error: type[Exception], setting: str = "", required: tuple[str, ...] = ("name",)
    ) -> None:
        self._base = base
        self._file = file
        self._error = error
        self._prefix = f"{setting}: " if setting else ""
        self._required = required

    def load(self, package: str) -> PartT:
        name = f"{package}.{self._file}"
        try:
            module = import_module(name)
        except ModuleNotFoundError as error:
            if error.name not in (name, package):
                raise   # файл нашёлся, но сам не смог что-то импортировать: ошибка в нём или не стоит его зависимость
            raise self._error(f"{self._prefix}{name}: module not found") from error
        classes = [
            value
            for value in vars(module).values()
            if isinstance(value, type) and issubclass(value, self._base) and value.__module__ == module.__name__
        ]
        if len(classes) != 1:
            raise self._error(f"{self._prefix}{name}: expected one {self._base.__name__} subclass, found {len(classes)}")
        part = classes[0]
        missing = [attribute for attribute in self._required if not getattr(part, attribute, "")]
        if missing:
            raise self._error(f"{self._prefix}{name}.{part.__name__}: {', '.join(missing)} not set")
        return part()


def repeated(names: Iterable[str]) -> list[str]:
    """Имена, которые встречаются больше одного раза, — по алфавиту."""
    return sorted(name for name, count in Counter(names).items() if count > 1)
