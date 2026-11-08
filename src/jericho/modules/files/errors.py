"""Отказы файловой системы: адаптер переводит ошибки ОС в них, а слой `Refusals` — в ответ модели."""

from __future__ import annotations

from jericho.core.errors import PortError


class FileSystemError(PortError):
    code = "file_system_error"


class NotFound(FileSystemError):
    code = "not_found"


class NotADirectory(FileSystemError):
    code = "not_a_directory"


class IsADirectory(FileSystemError):
    code = "is_a_directory"


class NotPermitted(FileSystemError):
    code = "not_permitted"


class AlreadyExists(FileSystemError):
    code = "already_exists"


class BrokenArchive(FileSystemError):
    code = "broken_archive"


class OpenFailed(FileSystemError):
    code = "open_failed"
