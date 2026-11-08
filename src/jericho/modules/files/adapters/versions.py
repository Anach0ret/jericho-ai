"""Прежние версии — копии в папке состояния ассистента, по дням: `versions/2026-10-16/203015-123456/<путь>`."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from jericho.modules.files.adapters.moments import MomentFolder


class DirectoryVersions:
    """Копия кладётся по полному пути файла внутри папки момента (`MomentFolder`)."""

    def __init__(self, directory: Path, now: Callable[[], datetime] = datetime.now) -> None:
        self._folder = MomentFolder(directory, now)

    def keep(self, path: Path) -> Path | None:
        copy = self._folder.place(path)
        shutil.copy2(path, copy)
        self._folder.close(copy)
        return copy
