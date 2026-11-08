"""Папка с копиями по моментам — общая у прежних версий и своей корзины: `<папка>/2026-10-16/203015-123456/<путь>`."""

from __future__ import annotations

import contextlib
import os
import stat
from collections.abc import Callable
from datetime import datetime
from pathlib import Path


class MomentFolder:
    """Место для копии по полному пути файла внутри папки момента: так видно, откуда она, и имена не сталкиваются.

    Всё здесь — в состоянии ассистента, поэтому только владельцу (E015): папки создаются с 700, у положенного
    снимаются права группы и остальных. Права владельца остаются — исполняемый файл вернётся исполняемым.
    Без этого копия файла 644 или папки 755 по обычному umask нарушала бы E015 (ревью 02.11.2026, П3a №13).
    """

    PRIVATE_DIR = 0o700
    OPEN = stat.S_IRWXG | stat.S_IRWXO

    def __init__(self, directory: Path, now: Callable[[], datetime] = datetime.now) -> None:
        self._directory = directory
        self._now = now

    def place(self, path: Path) -> Path:
        """Новое место для `path`; папки до него уже есть и закрыты."""
        moment = self._now()
        place = self._directory / f"{moment:%Y-%m-%d}" / f"{moment:%H%M%S-%f}" / path.relative_to(path.anchor)
        self._make_private(place.parent)
        return place

    def close(self, path: Path) -> None:
        """Положенное (файл или папку целиком) — только владельцу."""
        for item in (path, *path.rglob("*")) if path.is_dir() and not path.is_symlink() else (path,):
            if not item.is_symlink():
                item.chmod(stat.S_IMODE(item.stat().st_mode) & ~self.OPEN)

    def _make_private(self, directory: Path) -> None:
        """`mkdir(mode=…)` закрывает только последнюю папку, промежуточные получают umask — поэтому по одной."""
        missing = [parent for parent in (directory, *directory.parents) if not parent.exists()]
        for parent in reversed(missing):
            with contextlib.suppress(FileExistsError):      # соседний процесс успел раньше
                os.mkdir(parent, self.PRIVATE_DIR)
            parent.chmod(self.PRIVATE_DIR)       # umask мог отнять и у владельца
