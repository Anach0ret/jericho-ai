"""Удалить — всегда после «да» и всегда с возвратом: в корзину, а не навсегда."""

from __future__ import annotations

import hashlib
import json

from pydantic import Field

from jericho.core.tools.description import ToolDescription
from jericho.core.tools.request import ToolRequest
from jericho.core.tools.result import ToolRefusal, ToolResult
from jericho.core.tools.risk import Approval, Risk
from jericho.core.tools.tool import Tool
from jericho.modules.files.access import FileAccess
from jericho.modules.files.entities import Entry, Kind, Place
from jericho.modules.files.protocols import Trash


class DeleteRequest(ToolRequest):
    paths: list[str] = Field(
        min_length=1, max_length=50, description="Что удалить: файлы и папки целиком. Путь абсолютный или от первого корня."
    )


class Delete(Tool[DeleteRequest]):
    """«Да» спрашивает сама ручка (`Approval.TOOL`), чтобы согласие было на эти самые записи: если после вопроса
    файл изменился или в папке появилось новое, прежнее «да» не годится — вопрос задаётся снова."""

    name = "delete"
    risk = Risk.EFFECT
    approval = Approval.TOOL
    request_type = DeleteRequest
    description = ToolDescription(
        when="просят удалить файлы или папки.",
        does=(
            "убирает в корзину — вернуть можно. Всегда только после «да» пользователя: первый вызов отвечает "
            "needs_confirm со списком, ты называешь пользователю, что будет удалено, и ждёшь «да». Несколько путей — "
            "одним вызовом и одним вопросом."
        ),
        returns='{"ok": true, "deleted": [пути], "where": куда ушло — «корзина» или папка ассистента}.',
        refusals=(
            "needs_confirm (назови пользователю count и items и дождись «да»), root_itself (корень целиком не "
            "удаляется), not_found, outside_roots, forbidden_path, read_only_root (в том числе внутри папки), "
            "protected_path (внутри — файлы самого ассистента), not_permitted, no_roots."
        ),
    )

    ROOT_ITSELF = "root_itself"

    def __init__(self, access: FileAccess, trash: Trash) -> None:
        self._access = access
        self._trash = trash

    def _run(self, request: DeleteRequest) -> ToolResult:
        places = [self._place(raw) for raw in dict.fromkeys(request.paths)]
        entries = [self._access.filesystem.entry(place.path) for place in places]      # нет пути — not_found
        names = [place.shown() for place in places]
        self._access.ask(
            self.name, request.model_dump(), f"удалить в корзину {len(places)}: {', '.join(names[:5])}",
            [self._fingerprint(entry) for entry in entries], count=len(places), items=names,
        )
        where = [self._trash.discard(place.path) for place in places]
        return ToolResult.success(deleted=names, where=sorted(set(where)))

    def _fingerprint(self, entry: Entry) -> list[object]:
        """На что «да»: сама запись, а у папки — и всё под ней. Вложенный файл поправили или добавили — вопрос заново:
        у папки самой по себе время меняется только от её прямых записей (ревью 02.11.2026, П3a №12)."""
        if entry.kind is not Kind.DIRECTORY:
            return entry.fingerprint()
        filesystem = self._access.filesystem
        inside = [filesystem.entry(path).fingerprint() for path in filesystem.walk(entry.path, lambda _: True)]
        return [*entry.fingerprint(), hashlib.sha256(json.dumps(inside, ensure_ascii=False).encode()).hexdigest()]

    def _place(self, raw: str) -> Place:
        place = self._access.place(raw, remove=True)
        if place.path == place.root.path:
            raise ToolRefusal(self.ROOT_ITSELF, path=place.shown())
        return place
