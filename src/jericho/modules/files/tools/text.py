"""Текст файла для ручек: двоичное и огромное не читается, правка — только того, что точно в UTF-8."""

from __future__ import annotations

from jericho.core.tools.result import ToolRefusal
from jericho.modules.files.access import FileAccess
from jericho.modules.files.entities import Kind, Place
from jericho.modules.files.errors import IsADirectory


class TextFiles:
    BINARY = "binary_file"
    TOO_BIG = "too_big"
    NOT_UTF8 = "not_utf8"
    _PROBE = 8192        # нулевой байт в начале — признак двоичного файла, так же решает git

    def __init__(self, access: FileAccess, max_file_bytes: int) -> None:
        self._access = access
        self._max_file = max_file_bytes

    def read(self, place: Place) -> str:
        """Для чтения: байты не в UTF-8 заменяются знаком «�» — показать можно, сохранять так нельзя."""
        return self._bytes(place).decode("utf-8", errors="replace")

    def read_exact(self, place: Place) -> str:
        """Для правки: текст, который запишется обратно байт в байт, кроме изменённого."""
        try:
            return self._bytes(place).decode("utf-8")
        except UnicodeDecodeError:
            raise ToolRefusal(self.NOT_UTF8, path=place.shown()) from None

    def _bytes(self, place: Place) -> bytes:
        entry = self._access.filesystem.entry(place.path)
        if entry.kind is Kind.DIRECTORY:
            raise IsADirectory(place.shown())
        if entry.size > self._max_file:
            raise ToolRefusal(self.TOO_BIG, path=place.shown(), size=entry.size)
        data = self._access.filesystem.read(place.path)
        if b"\0" in data[: self._PROBE]:
            raise ToolRefusal(self.BINARY, path=place.shown(), size=entry.size)
        return data
