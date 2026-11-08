"""Правило файлов ассистента: настройки, ключи, журнал, сессии — только владельцу."""

from __future__ import annotations

import stat
import sys
from pathlib import Path

from jericho.core.checks.base import CheckMessage, Project


class FilesArePrivate:
    """E015: в папках ассистента (файлы машины, состояние, сеанс) ничто не открыто группе и остальным.

    Там ключи API, файл сессии Telegram — полный доступ к аккаунту, журнал и разговор. Прочитать их могла бы любая
    чужая учётная запись машины; так однажды осталась открытой сессия Telegram (23.10.2026, после упавшего входа).
    Замки (`*.lock`) пусты и не в счёт. Символьные ссылки не проходятся: они ведут за пределы папок.

    На Windows права задают списки доступа (ACL), а биты chmod ничего не значат: там правило проверяет, что папки
    лежат в профиле пользователя — его Windows закрывает от других учётных записей. Папка вне профиля — находка:
    её не закрывает никто (решение владельца 08.11.2026: полные гарантии — Linux, на Windows — разработка).
    """

    CODE = "jericho.E015"
    OPEN = stat.S_IRWXG | stat.S_IRWXO

    def __init__(self, system: str = sys.platform, home: Path | None = None) -> None:
        self._system = system
        self._home = home

    def run(self, project: Project) -> list[CheckMessage]:
        if self._system == "win32":
            return self._inside_profile(project)
        return self._modes(project)

    def _inside_profile(self, project: Project) -> list[CheckMessage]:
        home = self._home or Path.home()
        return [
            CheckMessage(self.CODE, root.as_posix(), f"вне профиля пользователя ({home.as_posix()}): на Windows эту папку от "
                         "других учётных записей не закрывает никто — перенеси её в профиль (убери XDG_* из окружения) или "
                         "закрой правами доступа сам")
            for root in project.private_dirs
            if not root.resolve().is_relative_to(home.resolve())
        ]

    def _modes(self, project: Project) -> list[CheckMessage]:
        messages: list[CheckMessage] = []
        for root in project.private_dirs:
            if not root.is_dir():
                continue
            for path in (root, *sorted(root.rglob("*"))):
                if path.is_symlink() or path.suffix == ".lock":
                    continue
                mode = path.stat().st_mode
                if mode & self.OPEN:
                    wanted = "700" if path.is_dir() else "600"
                    messages.append(CheckMessage(self.CODE, self._shown(path), f"открыто не только владельцу ({stat.S_IMODE(mode):o}): chmod {wanted} {self._shown(path)}"))
        return messages

    @staticmethod
    def _shown(path: Path) -> str:
        home = Path.home()
        return f"~/{path.relative_to(home).as_posix()}" if path.is_relative_to(home) else path.as_posix()
