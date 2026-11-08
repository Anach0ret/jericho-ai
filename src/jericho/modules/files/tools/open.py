"""Ручка `open_file`: открыть файл или папку программой по умолчанию. Только то, что открывается, а не запускается."""

from __future__ import annotations

import mimetypes

from pydantic import Field

from jericho.core.tools.description import ToolDescription
from jericho.core.tools.request import ToolRequest
from jericho.core.tools.result import ToolRefusal, ToolResult
from jericho.core.tools.risk import Risk
from jericho.core.tools.tool import Tool
from jericho.modules.files.access import FileAccess
from jericho.modules.files.entities import Entry, Kind, Place
from jericho.modules.files.protocols import Opener


class OpenPolicy:
    """Что можно отдать «двойному щелчку». Щелчок по скрипту или ярлыку запускает программу — это не «открыть».

    Белый список видов, а не чёрный список окончаний: неизвестное не открывается. Исполняемый бит — отказ при любом
    окончании. Страница из ненадёжного корня откроется в браузере и выполнит свой код — только после «да».
    """

    _LAUNCHERS = frozenset({
        ".desktop", ".sh", ".bash", ".zsh", ".fish", ".command", ".run", ".bin", ".appimage", ".flatpakref",
        ".exe", ".msi", ".bat", ".cmd", ".ps1", ".vbs", ".jar", ".deb", ".rpm", ".py", ".pl", ".rb", ".lnk", ".url",
        # Windows запускает и это — двойным щелчком, без бита «x» (его там нет): PATHEXT, Windows Script Host, реестр.
        ".com", ".scr", ".pif", ".cpl", ".msc", ".msp", ".hta", ".wsf", ".wsh", ".vbe", ".js", ".jse", ".reg",
        ".psm1", ".appref-ms", ".application", ".pkg", ".mpkg",
    })
    _MEDIA = frozenset({"text", "image", "audio", "video", "font"})
    _DOCUMENTS = (
        "application/pdf", "application/epub", "application/json", "application/xml", "application/rtf",
        "application/vnd.oasis.opendocument", "application/vnd.openxmlformats", "application/msword",
        "application/vnd.ms-", "application/zip", "application/x-tar", "application/gzip", "application/x-7z",
        "application/vnd.rar", "application/x-xz", "application/x-bzip", "application/zstd",
    )
    _ACTIVE = frozenset({"text/html", "image/svg+xml", "application/xhtml+xml"})

    LAUNCHER = "not_openable"
    UNKNOWN = "unknown_type"

    def check(self, place: Place, entry: Entry) -> bool:
        """Можно ли открыть. Вернёт True, если открывать можно только после «да» (активная страница из чужих)."""
        if entry.kind is Kind.DIRECTORY:
            return False
        if entry.kind is not Kind.FILE or entry.executable or place.path.suffix.casefold() in self._LAUNCHERS:
            raise ToolRefusal(self.LAUNCHER, path=place.shown(), detail="это запускается, а не открывается")
        kind_of, _ = mimetypes.guess_type(place.path.name)
        if kind_of is None or not (kind_of.split("/")[0] in self._MEDIA or kind_of.startswith(self._DOCUMENTS)):
            raise ToolRefusal(self.UNKNOWN, path=place.shown(), type=kind_of or "неизвестен")
        return kind_of in self._ACTIVE and place.root.untrusted


class OpenFileRequest(ToolRequest):
    path: str = Field(min_length=1, max_length=1000, description="Файл или папка. Путь абсолютный или от первого корня.")


class OpenFile(Tool[OpenFileRequest]):
    name = "open_file"
    risk = Risk.NAVIGATE
    request_type = OpenFileRequest
    description = ToolDescription(
        when="просят открыть, показать на экране файл или папку: документ, картинку, видео, папку в файловом менеджере.",
        does=(
            "открывает программой по умолчанию — как двойной щелчок. Скрипты, ярлыки и программы не запускает. "
            "Что внутри файла, тебе не показывает — для этого read_file."
        ),
        returns='{"ok": true, "path", "kind": file|dir}.',
        refusals=(
            "not_openable (это программа или скрипт — не запускаю, скажи об этом), unknown_type (вид файла "
            "неизвестен), needs_confirm (страница из загрузок — спроси «да»), open_failed, not_found, "
            "outside_roots, forbidden_path, protected_path, no_roots."
        ),
    )

    def __init__(self, access: FileAccess, opener: Opener, policy: OpenPolicy | None = None) -> None:
        self._access = access
        self._opener = opener
        self._policy = policy or OpenPolicy()

    def _run(self, request: OpenFileRequest) -> ToolResult:
        place = self._access.place(request.path)
        entry = self._access.filesystem.entry(place.path)
        if self._policy.check(place, entry):
            self._access.ask(self.name, request.model_dump(), f"открыть страницу из загрузок {place.shown()}", place.shown())
        self._opener.open(place.path)
        return ToolResult.success(path=place.shown(), kind=str(entry.kind))
