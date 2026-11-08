"""Что модуль «файлы» знает о файловой системе: корни, проверенные пути и записи папок."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Root:
    """Разрешённая папка. `path` — уже без `~`, `..` и символьных ссылок."""

    path: Path
    read_only: bool = False
    untrusted: bool = False


@dataclass(frozen=True, slots=True)
class Place:
    """Путь, который прошёл охрану: лежит внутри корня `root` и не задевает запретного."""

    path: Path
    root: Root

    def shown(self) -> str:
        """Как путь видит модель и пользователь: с `~` вместо домашней папки."""
        return shown(self.path)


class Kind(StrEnum):
    FILE = "file"
    DIRECTORY = "dir"
    LINK = "link"        # ссылка, которая ведёт наружу или в никуда: охрана её не пропустит
    OTHER = "other"      # сокет, устройство, канал


@dataclass(frozen=True, slots=True)
class Entry:
    """Запись папки: что это и сколько весит. Время — местное."""

    path: Path
    kind: Kind
    size: int
    modified: datetime
    executable: bool = False     # у файла стоит бит «x»: двойной щелчок его запустит, а не откроет

    def fingerprint(self) -> list[object]:
        """На что дано согласие: путь, вид, размер и время изменения. Файл поправили, в папке появилось новое — уже другое."""
        return [str(self.path), str(self.kind), self.size, f"{self.modified:%Y-%m-%d %H:%M:%S.%f}"]

    def to_dict(self) -> dict[str, object]:
        data: dict[str, object] = {"name": self.path.name, "kind": str(self.kind), "modified": f"{self.modified:%Y-%m-%d %H:%M}"}
        if self.kind is Kind.FILE:
            data["size"] = self.size
        return data


def shown(path: Path) -> str:
    home = Path.home()
    return f"~/{path.relative_to(home).as_posix()}" if path.is_relative_to(home) and path != home else path.as_posix()   # «/» на любой ОС


@dataclass(frozen=True, slots=True)
class Member:
    """Запись внутри архива — как она там названа, до распаковки. Имени из архива верить нельзя."""

    name: str
    size: int
    kind: Kind
    link: str = ""       # куда ведёт ссылка (только у `Kind.LINK`)


class ArchiveFormat(StrEnum):
    ZIP = "zip"
    TAR = "tar"
    TAR_GZ = "tar.gz"
    TAR_BZ2 = "tar.bz2"
    TAR_XZ = "tar.xz"
    TAR_ZST = "tar.zst"

    @classmethod
    def of(cls, path: Path) -> ArchiveFormat | None:
        """Вид архива по окончанию имени: «.tar.gz» и «.tgz» — одно и то же."""
        name = path.name.casefold()
        for suffix, format in _SUFFIXES:
            if name.endswith(suffix):
                return format
        return None

    @staticmethod
    def stem(path: Path) -> str:
        """Имя без окончания архива: «фото.tar.gz» → «фото» — так называется папка распаковки."""
        name = path.name
        for suffix, _ in _SUFFIXES:
            if name.casefold().endswith(suffix):
                return name[: -len(suffix)] or name
        return path.stem


_SUFFIXES = (
    (".tar.gz", ArchiveFormat.TAR_GZ), (".tgz", ArchiveFormat.TAR_GZ),
    (".tar.bz2", ArchiveFormat.TAR_BZ2), (".tbz2", ArchiveFormat.TAR_BZ2),
    (".tar.xz", ArchiveFormat.TAR_XZ), (".txz", ArchiveFormat.TAR_XZ),
    (".tar.zst", ArchiveFormat.TAR_ZST), (".tzst", ArchiveFormat.TAR_ZST),
    (".tar", ArchiveFormat.TAR), (".zip", ArchiveFormat.ZIP),
)
