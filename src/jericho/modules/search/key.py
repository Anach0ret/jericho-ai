"""Ключ поисковика: из переменной окружения, иначе из файла. Читается при первом поиске, а не при сборке."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from jericho.modules.search.errors import NotConfigured


class SearchKey:
    def __init__(self, variable: str, file: Path | None, environment: Mapping[str, str]) -> None:
        self._variable = variable
        self._file = file
        self._environment = environment

    def value(self) -> str:
        key = self._environment.get(self._variable, "").strip() if self._variable else ""
        if not key and self._file is not None and self._file.is_file():
            key = self._file.read_text(encoding="utf-8").strip()
        if not key:
            raise NotConfigured(f"нет ключа поиска: переменная {self._variable} или файл {self._file}")
        return key
