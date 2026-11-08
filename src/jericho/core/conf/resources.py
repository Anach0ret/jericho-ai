"""Файл, названный в настройках через пакет: «пакет:путь внутри пакета»."""

from __future__ import annotations

from importlib.util import find_spec
from pathlib import Path


class ResourceError(Exception):
    """Файл назван в настройках, но его нет или запись не того вида."""


def package_file(reference: str, setting: str) -> Path:
    """Файл по записи вида `home.settings:prompt/role.md`.

    Каркас, модули и проект стоят в разных местах, поэтому файл называется через пакет-владелец,
    а не путём на диске. `setting` — имя настройки для сообщения об ошибке.
    """
    package, separator, path = reference.partition(":")
    try:
        spec = find_spec(package) if separator else None
    except (ImportError, ValueError):
        spec = None
    if spec is None or not spec.submodule_search_locations:
        raise ResourceError(f"{setting}: '{reference}' must be 'package:path', and the package must be importable")
    file = Path(next(iter(spec.submodule_search_locations))) / path
    if not file.is_file():
        raise ResourceError(f"{setting}: '{reference}' — no file {file}")
    return file
