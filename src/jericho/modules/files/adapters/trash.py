"""Корзина: удалённое можно вернуть. На рабочем столе — общая корзина (freedesktop), на сервере — своя папка."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from send2trash import TrashPermissionError, send2trash

from jericho.modules.files.adapters.moments import MomentFolder
from jericho.modules.files.errors import NotPermitted


class FreedesktopTrash:
    """Та же корзина, что у файлового менеджера: вернуть можно из него. Стандарт — библиотека `send2trash`."""

    def discard(self, path: Path) -> str:
        try:
            send2trash(path)
        except TrashPermissionError as error:
            raise NotPermitted(f"{path}: корзина недоступна") from error
        return "корзина"


class DirectoryTrash:
    """Папка в состоянии ассистента, по дням: `trash/2026-10-16/203015-123456/<полный путь>` — как у версий.

    Для сервера и контейнера: там нет рабочего стола и общей корзины.
    """

    def __init__(self, directory: Path, now: Callable[[], datetime] = datetime.now) -> None:
        self._folder = MomentFolder(directory, now)

    def discard(self, path: Path) -> str:
        place = self._folder.place(path)
        shutil.move(path, place)
        self._folder.close(place)
        return str(place)
