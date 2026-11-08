"""Модуль ядра «чтение журнала»: модель отвечает на вопросы о том, что уже происходило."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from jericho.core.modules.config import ModuleConfig, ModuleServices
from jericho.core.tools.tool import Tool
from jericho.modules.journal_reader.tool import ReadJournal


class JournalReaderModule(ModuleConfig):
    """Сам журнал — часть каркаса: в него пишется каждый вызов. Модуль даёт модели ручку, чтобы его читать."""

    name = "journal_reader"

    def ready(self, services: ModuleServices) -> None:
        self._services = services

    def tools(self) -> Sequence[Tool[Any]]:
        return (ReadJournal(self._services.journal, self._services.tools, foreign=self._services.core.foreign),)
