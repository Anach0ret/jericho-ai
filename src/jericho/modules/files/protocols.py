"""Порты модуля «файлы»: что ручкам нужно от файловой системы. Пути сюда приходят уже проверенные охраной."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import Protocol

from jericho.modules.files.entities import ArchiveFormat, Entry, Member


class FileSystem(Protocol):
    """Чтение файловой системы. Ошибки — наследники `FileSystemError`, не `OSError`."""

    def entry(self, path: Path) -> Entry: ...

    def entries(self, directory: Path) -> list[Entry]:
        """Записи папки, без вложенных."""
        ...

    def walk(self, directory: Path, enter: Callable[[Path], bool]) -> Iterator[Path]:
        """Все пути под папкой, в глубину. В папку, для которой `enter` ответил «нет», обход не заходит."""
        ...

    def read(self, path: Path) -> bytes: ...


class FileChanger(Protocol):
    """Изменение файловой системы. Отдельно от чтения: «вхолостую» подменяется только эта половина."""

    def make_dir(self, path: Path) -> None:
        """Папка вместе с недостающими родителями; уже есть — не ошибка."""
        ...

    def create(self, path: Path, data: bytes) -> None:
        """Новый файл. Уже есть — `AlreadyExists`: существующее этим путём не затирается."""
        ...

    def replace(self, path: Path, data: bytes) -> None:
        """Переписать файл атомарно: читающий видит либо прежнее содержимое, либо новое, но не половину."""
        ...

    def copy(self, source: Path, target: Path) -> None:
        """Файл или папку целиком — ровно в `target`. Папка в `target` уже есть — `AlreadyExists`."""
        ...

    def move(self, source: Path, target: Path) -> None:
        """Ровно в `target`; файл на месте `target` заменяется."""
        ...


class Versions(Protocol):
    """Прежние версии файлов: перед правкой или заменой файл копируется сюда, и правку можно отменить."""

    def keep(self, path: Path) -> Path | None:
        """Сохранить текущее содержимое; вернуть, где лежит копия. `None` — не сохранялось (вхолостую)."""
        ...


class Trash(Protocol):
    """Удаление с возвратом: путь уходит туда, откуда его можно достать."""

    def discard(self, path: Path) -> str:
        """Убрать путь; вернуть, где его теперь искать, — для ответа пользователю."""
        ...


class Archiver(Protocol):
    """Архивы. Что распаковывать и что класть, решают ручки: сюда приходят уже проверенные списки."""

    def members(self, archive: Path) -> list[Member]: ...

    def unpack(self, archive: Path, target: Path, names: Sequence[str]) -> None:
        """Только названные записи — в новую папку `target`; её ещё нет. Сбой — папки не остаётся."""
        ...

    def pack(self, archive: Path, items: Sequence[tuple[Path, str]], format: ArchiveFormat) -> None:
        """Новый архив из пар «файл или папка на диске — имя в архиве». Архив уже есть — `AlreadyExists`."""
        ...


class Opener(Protocol):
    """Открыть путь программой по умолчанию — как двойной щелчок в файловом менеджере."""

    def open(self, path: Path) -> None: ...
