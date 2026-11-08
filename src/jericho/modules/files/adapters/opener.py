"""Открытие командой системы (`gio open`, `xdg-open`): она сама выбирает программу по виду файла."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from jericho.core.services.runner import CommandError, CommandRunner
from jericho.modules.files.errors import OpenFailed


class CommandOpener:
    def __init__(self, runner: CommandRunner, command: Sequence[str]) -> None:
        self._runner = runner
        self._command = tuple(command)

    def open(self, path: Path) -> None:
        try:
            # Не ждём конца: команда может висеть, пока открыта программа.
            self._runner.launch([*self._command, str(path)])
        except CommandError as error:
            raise OpenFailed(str(error)) from error
