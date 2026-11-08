"""Ключ API: в настройках лежит только имя переменной окружения или путь к файлу, сам ключ — вне настроек."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from jericho.core.agent.protocols import AgentBackendError


class EnvironmentKey:
    """Читает ключ при первом обращении, а не при сборке: без ключа работают `check`, `prompt` и ручки из терминала.

    Сначала переменная окружения, потом файл: ассистенту, которого запускает рабочий стол, переменную не передать
    без записи ключа в конфиг. Ни переменная, ни файл не названы — ключ не нужен (Ollama).
    """

    def __init__(self, variable: str, environment: Mapping[str, str], file: Path | None = None) -> None:
        self._variable = variable
        self._environment = environment
        self._file = file

    def value(self) -> str:
        key = self._environment.get(self._variable, "").strip() or self._from_file()
        if (self._variable or self._file) and not key:
            raise AgentBackendError(f"API key is not set: put it into the environment variable {self._variable} or the file {self._file}")
        return key

    def _from_file(self) -> str:
        return self._file.read_text(encoding="utf-8").strip() if self._file is not None and self._file.is_file() else ""
