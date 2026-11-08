"""Ручки архивов: распаковать в новую папку и запаковать в новый архив. Ничего существующего не затирают."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path, PurePosixPath

from pydantic import Field

from jericho.core.tools.description import ToolDescription
from jericho.core.tools.request import ToolRequest
from jericho.core.tools.result import ToolRefusal, ToolResult
from jericho.core.tools.risk import Risk
from jericho.core.tools.tool import Tool
from jericho.modules.files.access import FileAccess
from jericho.modules.files.entities import ArchiveFormat, Kind, Member, Place
from jericho.modules.files.errors import AlreadyExists
from jericho.modules.files.protocols import Archiver

_FORMATS = ", ".join(f".{format}" for format in ArchiveFormat)
_COMMON = "outside_roots, forbidden_path, protected_path, read_only_root, not_found, not_permitted, no_roots"


class UnpackRequest(ToolRequest):
    archive: str = Field(min_length=1, max_length=1000, description="Архив. Путь абсолютный или от первого корня.")
    target: str = Field(
        default="",
        max_length=1000,
        description="Новая папка для содержимого. Пусто — рядом с архивом, под его именем без окончания.",
    )


class Unpack(Tool[UnpackRequest]):
    """Имена внутри архива — чужие данные: каждое проверяется до распаковки, и один опасный путь — отказ всему архиву.

    Запретное (`.git`, `.env`, ключи) не распаковывается, а пропускается: в архивах проектов оно обычное.
    """

    name = "unpack"
    risk = Risk.CHANGE
    request_type = UnpackRequest
    description = ToolDescription(
        when="просят распаковать, разархивировать, извлечь архив.",
        does=(
            f"распаковывает архив ({_FORMATS}) в новую папку; существующую не трогает. Запретное внутри "
            "(.git, .env, ключи) пропускает. Из загрузок в другую папку — только после «да»."
        ),
        returns='{"ok": true, "target": папка, "files": сколько распаковано, "top": что лежит сверху, "skipped": пропущенное}.',
        refusals=(
            "archive_unsafe (путь в архиве ведёт наружу — не распаковываю, скажи об этом), archive_too_big, "
            "too_many_files, broken_archive (не архив или повреждён), unknown_format (rar, 7z — не умею), "
            f"already_exists (папка уже есть — назови другую), needs_confirm, {_COMMON}."
        ),
    )

    UNSAFE = "archive_unsafe"
    TOO_BIG = "archive_too_big"
    TOO_MANY = "too_many_files"
    UNKNOWN = "unknown_format"

    def __init__(self, access: FileAccess, archiver: Archiver, max_bytes: int, max_files: int) -> None:
        self._access = access
        self._archiver = archiver
        self._max_bytes = max_bytes
        self._max_files = max_files

    def _run(self, request: UnpackRequest) -> ToolResult:
        archive = self._access.place(request.archive)
        if ArchiveFormat.of(archive.path) is None:
            raise ToolRefusal(self.UNKNOWN, path=archive.shown(), formats=_FORMATS)
        target = self._access.place(request.target or str(archive.path.parent / ArchiveFormat.stem(archive.path)), write=True)
        if target.path.exists():
            raise AlreadyExists(target.shown())
        members = self._archiver.members(archive.path)
        self._check(members, archive)
        chosen = [member for member in members if not self._denied(member)]
        self._ask(request, archive, target)
        self._access.seen(archive.root)
        self._archiver.unpack(archive.path, target.path, [member.name for member in chosen])
        skipped = sorted({member.name for member in members} - {member.name for member in chosen})
        return ToolResult.success(
            target=target.shown(),
            files=sum(member.kind is Kind.FILE for member in chosen),
            top=sorted({PurePosixPath(member.name).parts[0] for member in chosen if PurePosixPath(member.name).parts})[:20],
            **({"skipped": skipped[:20], "skipped_count": len(skipped)} if skipped else {}),
        )

    def _check(self, members: list[Member], archive: Place) -> None:
        """Целиком до распаковки: опасное имя, размер и число записей."""
        for member in members:
            if not self._inside(member.name) or (member.kind is Kind.LINK and not self._inside(self._link_target(member))):
                raise ToolRefusal(self.UNSAFE, path=archive.shown(), entry=member.name[:200])
            if member.kind is Kind.OTHER:
                raise ToolRefusal(self.UNSAFE, path=archive.shown(), entry=member.name[:200], detail="устройство или канал")
        if len(members) > self._max_files:
            raise ToolRefusal(self.TOO_MANY, path=archive.shown(), count=len(members), limit=self._max_files)
        size = sum(member.size for member in members)
        if size > self._max_bytes:
            raise ToolRefusal(self.TOO_BIG, path=archive.shown(), size=size, limit=self._max_bytes)

    @staticmethod
    def _inside(name: str) -> bool:
        """Относительный путь, который не поднимается выше папки распаковки ни на одном шаге."""
        path = PurePosixPath(name.replace("\\", "/"))
        if path.is_absolute() or (path.parts and ":" in path.parts[0]):
            return False
        depth = 0
        for part in path.parts:
            depth += -1 if part == ".." else 0 if part == "." else 1
            if depth < 0:
                return False
        return True

    @staticmethod
    def _link_target(member: Member) -> str:
        """Куда ведёт ссылка, считая от папки распаковки: относительная — от папки самой ссылки."""
        if member.link.startswith("/"):
            return member.link
        return str(PurePosixPath(member.name).parent / member.link)

    def _denied(self, member: Member) -> bool:
        """Запретное имя — или ссылка на запретное: `visible.txt → .env` вынесла бы `.env` под чужим именем (ревью 02.11.2026).
        Цель ссылки проверяется в обоих прочтениях: у символьной она от папки ссылки, у жёсткой — от корня архива."""
        names = [member.name, *((member.link, self._link_target(member)) if member.kind is Kind.LINK else ())]
        return any(self._access.guard.denied_name(part) for name in names for part in PurePosixPath(name).parts)

    def _ask(self, request: UnpackRequest, archive: Place, target: Place) -> None:
        """Из ненадёжного корня в надёжный файлы стали бы «своими» — на это всегда нужно «да». Иначе — как у правок:
        «да», только если в фразе читали чужой текст. Один вопрос, не два: «да» на первый покрывает и второй."""
        arguments, subject = request.model_dump(), [archive.shown(), target.shown()]
        if archive.root.untrusted and not target.root.untrusted:
            summary = f"распаковать {archive.shown()} из загрузок в {target.shown()}"
            self._access.ask(self.name, arguments, summary, subject, source=archive.shown(), target=target.shown())
        else:
            self._access.ask_if_foreign(self.name, arguments, f"распаковать {archive.shown()}", subject)


class PackRequest(ToolRequest):
    sources: list[str] = Field(min_length=1, max_length=50, description="Что запаковать: файлы и папки целиком.")
    archive: str = Field(
        min_length=1,
        max_length=1000,
        description=f"Новый архив; вид — по окончанию имени: {_FORMATS}. Без окончания — допиши .zip.",
    )


class Pack(Tool[PackRequest]):
    name = "pack"
    risk = Risk.CHANGE
    request_type = PackRequest
    description = ToolDescription(
        when="просят запаковать, заархивировать, сжать файлы или папки.",
        does=(
            "создаёт новый архив; существующий не затирает. Запретное (.git, .env, ключи) в архив не кладёт — так "
            "секреты не уходят вместе с архивом; папку с файлами самого ассистента внутри не берёт (protected_path). "
            "Из загрузок в другую папку — только после «да»."
        ),
        returns='{"ok": true, "archive", "files": сколько файлов в архиве, "size": размер архива}.',
        refusals=f"unknown_format (назови окончание из списка), already_exists, too_many_files, needs_confirm, {_COMMON}.",
    )

    def __init__(self, access: FileAccess, archiver: Archiver, max_files: int) -> None:
        self._access = access
        self._archiver = archiver
        self._max_files = max_files

    def _run(self, request: PackRequest) -> ToolResult:
        archive = self._access.place(request.archive, write=True)
        format = ArchiveFormat.of(archive.path)
        if format is None:
            raise ToolRefusal(Unpack.UNKNOWN, path=archive.shown(), formats=_FORMATS)
        if archive.path.exists():
            raise AlreadyExists(archive.shown())
        sources = [self._access.place(raw, whole=True) for raw in request.sources]
        items = [item for source in sources for item in self._items(source)]
        if len(items) > self._max_files:
            raise ToolRefusal(Unpack.TOO_MANY, count=len(items), limit=self._max_files)
        self._ask(request, archive, sources)
        self._access.changer.make_dir(archive.path.parent)
        self._archiver.pack(archive.path, items, format)
        files = sum(not path.is_dir() for path, _ in items)
        size = archive.path.stat().st_size if archive.path.exists() else 0
        return ToolResult.success(archive=archive.shown(), files=files, size=size)

    def _ask(self, request: PackRequest, archive: Place, sources: Sequence[Place]) -> None:
        """Архив из загрузок в доверенной папке — те же «свои» чужие файлы, что у распаковки: всегда «да»."""
        arguments, summary = request.model_dump(), f"создать архив {archive.shown()}"
        adopted = [source.shown() for source in sources if self._access.guard.untrusted(source)]
        if adopted and not archive.root.untrusted:
            self._access.ask(self.name, arguments, f"{summary} из загрузок: {', '.join(adopted[:5])}", archive.shown(), untrusted=adopted)
        else:
            self._access.ask_if_foreign(self.name, arguments, summary, archive.shown())

    def _items(self, source: Place) -> list[tuple[Path, str]]:
        """Сам путь и всё под ним, что охрана разрешает видеть; имя в архиве — от родителя источника."""
        base = source.path.parent
        items = [(source.path, source.path.name)]
        if source.path.is_dir():
            walked = self._access.filesystem.walk(source.path, lambda directory: self._access.guard.allows(directory, source.root))
            items += [(path, str(path.relative_to(base))) for path in walked if self._access.guard.allows(path, source.root)]
        return items
