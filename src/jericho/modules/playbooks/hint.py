"""Подсказка памятки из кода: ответ ручки с адресом сайта, у которого есть памятка, напоминает о ней."""

from __future__ import annotations

from urllib.parse import urlsplit

from jericho.core.tools.dispatcher import CallHandler, ToolCall
from jericho.core.tools.result import ToolResult
from jericho.modules.playbooks.shelf import PlaybookShelf


def site_of(url: str) -> str:
    return (urlsplit(url).hostname or "").casefold().removeprefix("www.")


class PlaybookHint:
    """Слой вокруг вызова ручки. Журнал 29.10.2026: по одному правилу в промпте модель открыла памятку 2 раза из 8.

    Адрес — параметр `url` вызова или `page.url` ответа (открыли страницу, нажали ссылку). Один раз за фразу на
    памятку: процесс ручек живёт одну фразу. Прочитала памятку сама (`playbook_show`) — больше не напоминаем.
    """

    SHOW = "playbook_show"

    def __init__(self, shelf: PlaybookShelf) -> None:
        self._shelf = shelf
        self._told: set[str] = set()

    def __call__(self, handle: CallHandler) -> CallHandler:
        def hinted(call: ToolCall) -> ToolResult:
            result = handle(call)
            if call.tool.name == self.SHOW:
                self._told.add(str(call.arguments.get("playbook")))
                return result
            if not result.ok:
                return result
            site = site_of(self._address(call, result))
            playbook = next(
                (item for item in self._shelf.all() if item.accepted and item.site and self._covers(item.site, site)), None,
            )
            if playbook is None or playbook.id in self._told:
                return result
            self._told.add(playbook.id)
            reminder = {"id": playbook.id, "title": playbook.title, "hint": "есть памятка для этого сайта — playbook_show до следующего действия"}
            return ToolResult(ok=True, data={**result.data, "playbook": reminder}, images=result.images)
        return hinted

    @staticmethod
    def _address(call: ToolCall, result: ToolResult) -> str:
        url = call.arguments.get("url")
        if isinstance(url, str):
            return url
        page = result.data.get("page")
        return str(page.get("url", "")) if isinstance(page, dict) else ""

    @staticmethod
    def _covers(playbook_site: str, site: str) -> bool:
        """Тот же сайт или его поддомен: памятка «example.org» подходит и к «lms.example.org»."""
        return bool(site) and (site == playbook_site or site.endswith(f".{playbook_site}"))
