"""Имена, которые Win32 читает иначе, чем написано: поток NTFS и точка в конце. Правило Windows проверяется на любой
ОС — охране передаётся `system="win32"`."""

import sys
from pathlib import Path

import pytest

from jericho.core.tools.result import ToolRefusal
from jericho.modules.files.entities import Root
from jericho.modules.files.guard import PathGuard
from jericho.modules.files.settings import DEFAULT_DENY


@pytest.fixture
def windows(tree: Path) -> PathGuard:
    return PathGuard([Root(tree / "docs")], DEFAULT_DENY, system="win32")


@pytest.mark.parametrize("raw", ["project/.env::$DATA", "project/.env:secret", "project/.env.", "project/.env ", "Obsidian./План.md"])
def test_names_win32_reads_otherwise_are_forbidden(windows: PathGuard, raw: str) -> None:
    with pytest.raises(ToolRefusal, match="forbidden_path"):
        windows.place(raw)


def test_ordinary_names_and_dots_pass(windows: PathGuard) -> None:
    assert windows.place("Obsidian/План.md").path.name == "План.md"
    assert windows.place("Obsidian/../Obsidian/План.md").path.name == "План.md"


@pytest.mark.skipif(sys.platform == "win32", reason="«:» в имени файла — POSIX; на Windows такого имени нет")
def test_colon_is_an_ordinary_character_elsewhere(tree: Path) -> None:
    linux = PathGuard([Root(tree / "docs")], DEFAULT_DENY, system="linux")

    assert linux.place("время 10:30.txt").path.name == "время 10:30.txt"
