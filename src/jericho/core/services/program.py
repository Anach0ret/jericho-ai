"""Как ассистент запускается не из терминала: таймером, службой системы."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from jericho.core.services.phrase_deadline import PhraseDeadline


@dataclass(frozen=True, slots=True)
class Program:
    """Всё, чтобы описать запуск ассистента для внешнего планировщика: без оболочки, без PATH, без переменных терминала."""

    RUN_VARIABLE: ClassVar[str] = "JERICHO_RUN"     # запуск, которому служит процесс: сервер ручек получает его от фразы
    DEADLINE_VARIABLE: ClassVar[str] = PhraseDeadline.VARIABLE     # срок фразы: самостоятельному запуску он не нужен

    name: str                          # имя команды проекта: «home»
    command: tuple[str, ...]           # чем запускать: «…/python -m jericho»
    environment: Mapping[str, str]     # переменные проекта: модуль настроек, вариант, папка файлов машины
    config_dir: Path                   # файлы этой машины: ~/.config/<проект>
    user_config_home: Path             # папка настроек ОС (на Linux ~/.config) — там же пользовательские таймеры systemd

    def detached(self, *arguments: str) -> tuple[str, ...]:
        """Команда ассистента как новый, свой запуск — даже из сервера ручек, который служит чужой фразе.

        Без этого запущенное унаследовало бы запуск фразы (`RUN_VARIABLE`): общие журнал и подтверждения, — и её срок
        (`DEADLINE_VARIABLE`): план из нескольких фраз упирался в остаток той, что его запустила (ревью 07.11.2026, №1).
        """
        return ("env", "-u", self.RUN_VARIABLE, "-u", self.DEADLINE_VARIABLE, *self.command, *arguments)

    def module(self, name: str, *arguments: str) -> tuple[str, ...]:
        """Запуск модуля Python тем же интерпретатором, что и ассистент: `command` — «…/python -m jericho»."""
        return (self.command[0], "-m", name, *arguments)
