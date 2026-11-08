"""Папки самого ассистента: его файлы ручки не трогают при любых корнях."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from pathlib import Path


class OwnPaths:
    """Состояние, сеансы всех пользователей, файлы машины, код — и то, что добавили модули и навыки.

    Ядро заполняет основу при сборке; модуль или навык со своей служебной папкой (папка обмена с транспортом,
    токены) добавляет её в `ready()`. Охрана файлов читает список во время вызова, когда собраны все: поэтому
    порядок модулей в `INSTALLED_MODULES` на защиту не влияет.
    """

    def __init__(self, paths: Iterable[Path] = ()) -> None:
        self._paths = list(paths)

    def add(self, *paths: Path) -> None:
        self._paths.extend(paths)

    def __iter__(self) -> Iterator[Path]:
        return iter(tuple(self._paths))
