"""Brave Search API — веб-поиск по ключу. Запрос — стандартным `urllib.request`: одного GET хватает без библиотек."""

from __future__ import annotations

import html
import re
import urllib.parse
import urllib.request
from typing import Any, ClassVar

from jericho.modules.search.adapters.http import Fetch, fetch_url, records, request_json
from jericho.modules.search.entities import Freshness, SearchHit
from jericho.modules.search.key import SearchKey


class BraveSearch:
    URL = "https://api.search.brave.com/res/v1/web/search"
    _FRESHNESS: ClassVar[dict[Freshness, str]] = {Freshness.DAY: "pd", Freshness.WEEK: "pw", Freshness.MONTH: "pm", Freshness.YEAR: "py"}
    _TAGS = re.compile(r"<[^>]+>")      # в выдержках Brave выделяет найденное тегами <strong>

    def __init__(self, key: SearchKey, country: str = "", language: str = "", timeout: float = 10.0, fetch: Fetch = fetch_url) -> None:
        self._key = key
        self._country = country
        self._language = language
        self._timeout = timeout
        self._fetch = fetch

    def search(self, query: str, count: int, freshness: Freshness) -> list[SearchHit]:
        parameters = {"q": query, "count": str(count), "safesearch": "moderate"}
        if freshness in self._FRESHNESS:
            parameters["freshness"] = self._FRESHNESS[freshness]
        if self._country:
            parameters["country"] = self._country
        if self._language:
            parameters["search_lang"] = self._language
        request = urllib.request.Request(
            f"{self.URL}?{urllib.parse.urlencode(parameters)}",
            headers={"Accept": "application/json", "X-Subscription-Token": self._key.value()},
        )
        data = request_json(self._fetch, request, self._timeout)
        web = data.get("web") if isinstance(data, dict) else None
        results = records(web.get("results") if isinstance(web, dict) else None)
        return [self._hit(item) for item in results][:count]

    def _hit(self, item: dict[str, Any]) -> SearchHit:
        return SearchHit(
            title=self._plain(item.get("title")), url=str(item.get("url", "")),
            snippet=self._plain(item.get("description")), age=self._plain(item.get("age")),
        )

    def _plain(self, value: object) -> str:
        return html.unescape(self._TAGS.sub("", value)) if isinstance(value, str) else ""
