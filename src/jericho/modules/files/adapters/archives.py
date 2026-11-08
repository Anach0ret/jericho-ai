"""Архивы стандартной библиотекой: `zipfile` и `tarfile` (zstd — с Python 3.14)."""

from __future__ import annotations

import os
import shutil
import stat
import tarfile
import tempfile
import zipfile
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO

from jericho.modules.files.entities import ArchiveFormat, Kind, Member
from jericho.modules.files.errors import AlreadyExists, BrokenArchive, NotFound, NotPermitted


class StandardArchiver:
    def members(self, archive: Path) -> list[Member]:
        with self._broken(archive):
            if zipfile.is_zipfile(archive):
                with zipfile.ZipFile(archive) as file:
                    return [self._zip_member(info) for info in file.infolist()]
            with tarfile.open(archive) as file:
                return [self._tar_member(info) for info in file.getmembers()]

    def unpack(self, archive: Path, target: Path, names: Sequence[str]) -> None:
        """Во временную папку рядом, потом переименование: сбой посередине не оставляет полураспакованного."""
        if target.exists():
            raise AlreadyExists(str(target))
        temporary = Path(tempfile.mkdtemp(dir=target.parent, prefix=f".{target.name}."))
        try:
            with self._broken(archive):
                if zipfile.is_zipfile(archive):
                    with zipfile.ZipFile(archive) as file:
                        file.extractall(temporary, members=names)
                else:
                    with tarfile.open(archive) as file:
                        file.extractall(temporary, members=self._chosen_tar(file, names), filter="data")
            temporary.rename(target)
        except BaseException:
            shutil.rmtree(temporary, ignore_errors=True)
            raise

    @staticmethod
    def _chosen_tar(file: tarfile.TarFile, names: Sequence[str]) -> list[tarfile.TarInfo]:
        """Выбранные записи. Жёсткая ссылка на запись, которая не распаковывается, — нет: не найдя цель на диске,
        `tarfile` достал бы её содержимое из архива под именем ссылки (ревью 02.11.2026, П3a №5). Выкидываем до
        неподвижной точки: в цепочке `three → two → one → .env` отброшенная `two` уносит и `three` (ревью 07.11.2026).
        Фильтр «data» — ещё один замок после проверки ручки: без абсолютных путей, «..», устройств и ссылок наружу."""
        chosen = set(names)
        members = [info for info in file.getmembers() if info.name in chosen]
        while True:
            kept = {info.name for info in members}
            remaining = [info for info in members if not (info.islnk() and info.linkname not in kept)]
            if len(remaining) == len(members):
                return remaining
            members = remaining

    def pack(self, archive: Path, items: Sequence[tuple[Path, str]], format: ArchiveFormat) -> None:
        """Имя занимается исключительно (`O_EXCL`), и архив пишется в этот самый открытый файл, а не заново по пути.
        Удаляется при сбое только он: файл, которым тем временем подменили путь, цел (ревью 02.11.2026, П3a №14;
        07.11.2026, №4). Между сверкой и удалением остаётся узкое окно — предел POSIX: удалить «по дескриптору» нельзя.
        Удаляется уже закрытый: Windows открытый файл не удалит — сбой оставлял недописанный архив и прятал исходную
        ошибку за `PermissionError`; какой файл наш, помнит `fstat`, снятый до закрытия."""
        try:
            descriptor = os.open(archive, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        except FileExistsError as error:
            raise AlreadyExists(str(archive)) from error
        created = os.fstat(descriptor)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                self._write(stream, items, format)
        except BaseException:
            self._remove_own(archive, created)
            raise

    @staticmethod
    def _remove_own(archive: Path, created: os.stat_result) -> None:
        try:
            if os.path.samestat(os.stat(archive), created):
                archive.unlink()
        except FileNotFoundError:
            pass

    def _write(self, stream: BinaryIO, items: Sequence[tuple[Path, str]], format: ArchiveFormat) -> None:
        if format is ArchiveFormat.ZIP:
            with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as file:
                for path, name in items:
                    file.write(path, name)
        else:
            with self._new_tar(stream, format) as file:
                for path, name in items:
                    file.add(path, name, recursive=False)

    @staticmethod
    def _new_tar(stream: BinaryIO, format: ArchiveFormat) -> tarfile.TarFile:
        """Режим — буквальной строкой в каждой ветке: так его понимает проверка типов `tarfile.open`."""
        match format:
            case ArchiveFormat.TAR_GZ:
                return tarfile.open(fileobj=stream, mode="w:gz")
            case ArchiveFormat.TAR_BZ2:
                return tarfile.open(fileobj=stream, mode="w:bz2")
            case ArchiveFormat.TAR_XZ:
                return tarfile.open(fileobj=stream, mode="w:xz")
            case ArchiveFormat.TAR_ZST:
                # Режим «zst» есть в tarfile с Python 3.14; заглушки typeshed у basedpyright 1.40 его ещё не знают.
                return tarfile.open(fileobj=stream, mode="w:zst")  # pyright: ignore[reportCallIssue, reportArgumentType]
            case _:
                return tarfile.open(fileobj=stream, mode="w")

    @staticmethod
    def _zip_member(info: zipfile.ZipInfo) -> Member:
        if stat.S_ISLNK(info.external_attr >> 16):
            return Member(info.filename, info.file_size, Kind.LINK)
        return Member(info.filename, info.file_size, Kind.DIRECTORY if info.is_dir() else Kind.FILE)

    @staticmethod
    def _tar_member(info: tarfile.TarInfo) -> Member:
        if info.issym() or info.islnk():
            return Member(info.name, 0, Kind.LINK, info.linkname)
        kind = Kind.FILE if info.isfile() else Kind.DIRECTORY if info.isdir() else Kind.OTHER
        return Member(info.name, info.size, kind)

    @staticmethod
    @contextmanager
    def _broken(archive: Path) -> Iterator[None]:
        try:
            yield
        except FileNotFoundError as error:
            raise NotFound(str(archive)) from error
        except PermissionError as error:
            raise NotPermitted(str(archive)) from error
        except (zipfile.BadZipFile, tarfile.TarError, EOFError, OSError, KeyError) as error:
            raise BrokenArchive(f"{archive}: {error}") from error
