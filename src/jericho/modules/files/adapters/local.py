"""Файловая система этой машины — стандартными `os` и `pathlib`."""

from __future__ import annotations

import errno
import os
import shutil
import stat
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import ClassVar

from jericho.modules.files.entities import Entry, Kind
from jericho.modules.files.errors import AlreadyExists, FileSystemError, IsADirectory, NotADirectory, NotFound, NotPermitted


class LocalFileSystem:
    _ERRORS: ClassVar[dict[int, type[FileSystemError]]] = {
        errno.ENOENT: NotFound,
        errno.ENOTDIR: NotADirectory,
        errno.EISDIR: IsADirectory,
        errno.EACCES: NotPermitted,
        errno.EPERM: NotPermitted,
        errno.EEXIST: AlreadyExists,
        errno.ENOTEMPTY: AlreadyExists,
    }

    def entry(self, path: Path) -> Entry:
        with self._os_errors(path):
            return self._entry(path)

    def entries(self, directory: Path) -> list[Entry]:
        with self._os_errors(directory):
            return [self._entry(Path(item.path)) for item in os.scandir(directory)]

    def walk(self, directory: Path, enter: Callable[[Path], bool]) -> Iterator[Path]:
        with self._os_errors(directory):
            if not directory.is_dir():
                raise NotADirectory(str(directory))
        for top, directories, files in os.walk(directory):     # недоступные вложенные папки os.walk пропускает сам
            here = Path(top)
            directories[:] = sorted(name for name in directories if enter(here / name))
            yield from (here / name for name in (*directories, *sorted(files)))

    def read(self, path: Path) -> bytes:
        with self._os_errors(path):
            return path.read_bytes()

    def make_dir(self, path: Path) -> None:
        with self._os_errors(path):
            path.mkdir(parents=True, exist_ok=True)

    def create(self, path: Path, data: bytes) -> None:
        with self._os_errors(path), path.open("xb") as file:
            file.write(data)

    def replace(self, path: Path, data: bytes) -> None:
        """Во временный файл рядом, затем `os.replace` — атомарная подмена в пределах одной файловой системы."""
        with self._os_errors(path):
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as file:
                temporary = Path(file.name)
                file.write(data)
                file.flush()
                os.fsync(file.fileno())
            try:
                shutil.copymode(path, temporary)
                os.replace(temporary, path)
            except BaseException:
                temporary.unlink(missing_ok=True)
                raise

    def copy(self, source: Path, target: Path) -> None:
        with self._os_errors(target):
            if source.is_dir():
                shutil.copytree(source, target, symlinks=True)
            else:
                shutil.copy2(source, target)

    def move(self, source: Path, target: Path) -> None:
        with self._os_errors(target):
            if target.is_dir():
                raise AlreadyExists(str(target))     # shutil.move положил бы внутрь — а просили ровно сюда
            shutil.move(source, target)

    @staticmethod
    def _entry(path: Path) -> Entry:
        try:
            info = path.stat()
        except FileNotFoundError:          # ссылка в никуда
            info = path.lstat()
            return Entry(path, Kind.LINK, 0, datetime.fromtimestamp(info.st_mtime).astimezone())
        kind = Kind.FILE if stat.S_ISREG(info.st_mode) else Kind.DIRECTORY if stat.S_ISDIR(info.st_mode) else Kind.OTHER
        executable = kind is Kind.FILE and bool(info.st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))
        return Entry(path, kind, info.st_size, datetime.fromtimestamp(info.st_mtime).astimezone(), executable)

    @contextmanager
    def _os_errors(self, path: Path) -> Iterator[None]:
        try:
            yield
        except OSError as error:
            raise self._ERRORS.get(error.errno or 0, FileSystemError)(f"{path}: {error.strerror}") from error
