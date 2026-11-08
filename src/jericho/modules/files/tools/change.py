"""Ручки изменения: создать папку или файл, поправить текст. Поправимо — прежняя версия сохраняется, «да» не нужно.

«Да» всё же спрашивается, если в этой фразе модель читала чужой текст: просьба изменить могла прийти оттуда.
"""

from __future__ import annotations

import hashlib

from pydantic import Field

from jericho.core.tools.description import ToolDescription
from jericho.core.tools.request import ToolRequest
from jericho.core.tools.result import ToolRefusal, ToolResult
from jericho.core.tools.risk import Risk
from jericho.core.tools.tool import Tool
from jericho.modules.files.access import FileAccess
from jericho.modules.files.entities import Kind
from jericho.modules.files.errors import AlreadyExists, IsADirectory
from jericho.modules.files.tools.text import TextFiles

_PATH = "Путь: абсолютный («~/Документы/план.md») или от первого разрешённого корня."
_FOREIGN = "needs_confirm (в этой фразе читали чужой текст — спроси пользователя и дождись «да»)"
_COMMON = "outside_roots, forbidden_path, read_only_root, not_permitted, no_roots"


class MakeDirRequest(ToolRequest):
    path: str = Field(min_length=1, max_length=1000, description=f"Новая папка; недостающие родители создаются. {_PATH}")


class MakeDir(Tool[MakeDirRequest]):
    name = "make_dir"
    risk = Risk.CHANGE
    request_type = MakeDirRequest
    description = ToolDescription(
        when="просят создать папку.",
        does="создаёт папку вместе с недостающими родительскими. Уже есть — ничего не делает и говорит об этом.",
        returns='{"ok": true, "path", "existed": true — папка уже была}.',
        refusals=f"already_exists (на этом месте файл), {_FOREIGN}, {_COMMON}.",
    )

    def __init__(self, access: FileAccess) -> None:
        self._access = access

    def _run(self, request: MakeDirRequest) -> ToolResult:
        place = self._access.place(request.path, write=True)
        if place.path.exists():
            if self._access.filesystem.entry(place.path).kind is not Kind.DIRECTORY:
                raise AlreadyExists(place.shown())
            return ToolResult.success(path=place.shown(), existed=True)
        self._access.ask_if_foreign(self.name, request.model_dump(), f"создать папку {place.shown()}", place.shown())
        self._access.changer.make_dir(place.path)
        return ToolResult.success(path=place.shown())


class CreateFileRequest(ToolRequest):
    path: str = Field(min_length=1, max_length=1000, description=f"Новый файл; недостающие папки создаются. {_PATH}")
    text: str = Field(default="", max_length=1_000_000, description="Содержимое. Пусто — пустой файл.")


class CreateFile(Tool[CreateFileRequest]):
    name = "create_file"
    risk = Risk.CHANGE
    request_type = CreateFileRequest
    description = ToolDescription(
        when="просят создать новый файл: заметку, список, черновик.",
        does="создаёт файл с текстом в UTF-8. Существующий файл не затирает никогда — для этого edit_file или write_file.",
        returns='{"ok": true, "path", "size"}.',
        refusals=f"already_exists (файл уже есть — спроси, дописать или заменить), {_FOREIGN}, {_COMMON}.",
    )

    def __init__(self, access: FileAccess) -> None:
        self._access = access

    def _run(self, request: CreateFileRequest) -> ToolResult:
        place = self._access.place(request.path, write=True)
        if place.path.exists():
            raise AlreadyExists(place.shown())
        self._access.ask_if_foreign(self.name, request.model_dump(), f"создать файл {place.shown()}", place.shown())
        data = request.text.encode()
        self._access.changer.make_dir(place.path.parent)
        self._access.changer.create(place.path, data)
        return ToolResult.success(path=place.shown(), size=len(data))


class EditFileRequest(ToolRequest):
    path: str = Field(min_length=1, max_length=1000, description=_PATH)
    old: str = Field(
        min_length=1,
        max_length=100_000,
        description=(
            "Кусок текста, который заменить, — точно как в файле, с пробелами и переносами. Прочитай файл "
            "read_file перед правкой. Чтобы дописать в конец, возьми последнюю строку и замени её на неё же с добавкой."
        ),
    )
    new: str = Field(max_length=1_000_000, description="Чем заменить. Пусто — удалить кусок.")
    every: bool = Field(default=False, description="Заменить все вхождения. По умолчанию кусок обязан встретиться ровно один раз.")


class EditFile(Tool[EditFileRequest]):
    name = "edit_file"
    risk = Risk.CHANGE
    request_type = EditFileRequest
    description = ToolDescription(
        when="просят поправить, дописать или убрать часть текста в существующем файле.",
        does=(
            "заменяет точный кусок текста; остальное в файле не трогает. Прежняя версия файла сохраняется — "
            "правку можно отменить."
        ),
        returns='{"ok": true, "path", "replaced": сколько вхождений заменено, "previous": где копия прежней версии}.',
        refusals=(
            "text_not_found (куска нет — перечитай файл), text_ambiguous (кусок встречается count раз — возьми "
            "кусок длиннее или every=true, если менять все), not_utf8, binary_file, too_big, not_found, "
            f"{_FOREIGN}, {_COMMON}."
        ),
    )

    NOT_FOUND = "text_not_found"
    AMBIGUOUS = "text_ambiguous"

    def __init__(self, access: FileAccess, max_file_bytes: int) -> None:
        self._access = access
        self._text = TextFiles(access, max_file_bytes)

    def _run(self, request: EditFileRequest) -> ToolResult:
        place = self._access.place(request.path, write=True)
        text = self._text.read_exact(place)
        count = text.count(request.old)
        if count == 0:
            raise ToolRefusal(self.NOT_FOUND, path=place.shown())
        if count > 1 and not request.every:
            raise ToolRefusal(self.AMBIGUOUS, path=place.shown(), count=count)
        self._access.ask_if_foreign(self.name, request.model_dump(), f"изменить файл {place.shown()}", hashlib.sha256(text.encode()).hexdigest())
        previous = self._access.keep_version(place)
        self._access.changer.replace(place.path, text.replace(request.old, request.new).encode())
        return ToolResult.success(path=place.shown(), replaced=count, previous=previous)


class WriteFileRequest(ToolRequest):
    path: str = Field(min_length=1, max_length=1000, description=f"Существующий файл. {_PATH}")
    text: str = Field(max_length=1_000_000, description="Новое содержимое целиком.")


class WriteFile(Tool[WriteFileRequest]):
    name = "write_file"
    risk = Risk.CHANGE
    request_type = WriteFileRequest
    description = ToolDescription(
        when="просят переписать существующий файл целиком. Поправить часть — edit_file, новый файл — create_file.",
        does="заменяет всё содержимое файла. Прежняя версия сохраняется — можно вернуть.",
        returns='{"ok": true, "path", "size", "previous": где копия прежней версии}.',
        refusals=f"not_found (файла нет — create_file), is_a_directory, {_FOREIGN}, {_COMMON}.",
    )

    def __init__(self, access: FileAccess) -> None:
        self._access = access

    def _run(self, request: WriteFileRequest) -> ToolResult:
        place = self._access.place(request.path, write=True)
        entry = self._access.filesystem.entry(place.path)
        if entry.kind is Kind.DIRECTORY:
            raise IsADirectory(place.shown())
        self._access.ask_if_foreign(self.name, request.model_dump(), f"переписать файл {place.shown()} целиком", entry.fingerprint())
        previous = self._access.keep_version(place)
        data = request.text.encode()
        self._access.changer.replace(place.path, data)
        return ToolResult.success(path=place.shown(), size=len(data), previous=previous)
