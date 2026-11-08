"""Типы полей настроек: то, что в файле пишут строкой, а в коде нужно готовым."""

from __future__ import annotations

import shlex
from pathlib import Path
from typing import Annotated

from pydantic import AfterValidator, BeforeValidator


def _expand(path: Path) -> Path:
    return path.expanduser()


def _split(value: object) -> object:
    """Команда строкой → программа и её аргументы; `~` в пути к программе раскрывается. Пустая строка — команды нет."""
    if not isinstance(value, str):
        return value
    words = shlex.split(value)
    if not words:
        return ()
    program, *arguments = words
    return (str(Path(program).expanduser()), *arguments)


ExpandedPath = Annotated[Path, AfterValidator(_expand)]
"""Путь; `~` раскрывается в домашнюю папку."""

CommandLine = Annotated[tuple[str, ...], BeforeValidator(_split)]
"""Команда для запуска: в файле — строка `~/.local/bin/zed --new`, в коде — кортеж аргументов."""
