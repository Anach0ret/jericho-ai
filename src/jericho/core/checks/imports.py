"""Какие модули импортирует файл — по тексту, без его выполнения."""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path


def python_files(directory: Path) -> Iterator[Path]:
    return (file for file in sorted(directory.rglob("*.py")) if "__pycache__" not in file.parts)


def imported_modules(file: Path, package: str = "", directory: Path | None = None) -> list[str]:
    """Полные имена модулей из `import x` и `from x import y`.

    Относительный импорт (`from ..other import x`) переводится в полное имя, если известно, какому пакету принадлежит
    папка (`package`, `directory`): иначе `from ..other_skill import tools` проходил мимо правил (ревью R12).
    Без них относительный импорт — имя `.`: о нём всё равно сообщат, а не пропустят.
    """
    tree = ast.parse(file.read_text(encoding="utf-8"), filename=str(file))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules.append(node.module)
        elif isinstance(node, ast.ImportFrom) and node.level > 0:
            base = _relative_base(file, package, directory, node.level)
            if node.module:
                modules.append(f"{base}.{node.module}" if base else f".{node.module}")
            else:
                modules.extend(f"{base}.{alias.name}" if base else f".{alias.name}" for alias in node.names)
    return modules


def _relative_base(file: Path, package: str, directory: Path | None, level: int) -> str:
    """Пакет, от которого считается относительный импорт файла; пусто — пакет неизвестен."""
    if not package or directory is None or not file.is_relative_to(directory):
        return ""
    parts = [*package.split("."), *file.relative_to(directory).with_suffix("").parts]
    parts = parts[:-1]                      # пакет файла: у `__init__.py` это он сам, у модуля — папка с ним
    if level - 1 > len(parts):
        return ""
    return ".".join(parts[: len(parts) - (level - 1)])


def is_within(module: str, package: str) -> bool:
    return module == package or module.startswith(package + ".")
