"""Tavily — поиск для ассистентов: бесплатно 1000 запросов в месяц. Запрос — стандартным `urllib.request`."""

from __future__ import annotations

import json
import urllib.request
from typing import Any

from jericho.modules.search.adapters.http import Fetch, fetch_url, records, request_json
from jericho.modules.search.entities import Freshness, SearchHit
from jericho.modules.search.key import SearchKey


class TavilySearch:
    URL = "https://api.tavily.com/search"
    _SNIPPET = 600      # Tavily отдаёт длинные куски страниц — модели хватит начала
    _LIMIT_CODES = (429, 432, 433)      # 432, 433 — у Tavily исчерпаны кредиты тарифа

    def __init__(self, key: SearchKey, country: str = "", timeout: float = 10.0, fetch: Fetch = fetch_url) -> None:
        self._key = key
        self._country = country
        self._timeout = timeout
        self._fetch = fetch

    def search(self, query: str, count: int, freshness: Freshness) -> list[SearchHit]:
        payload: dict[str, object] = {"query": query, "max_results": count, "search_depth": "basic"}
        if freshness is not Freshness.ANY:
            payload["time_range"] = str(freshness)
        if self._country:
            payload["country"] = self._country
        request = urllib.request.Request(
            self.URL,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self._key.value()}"},
            method="POST",
        )
        data = request_json(self._fetch, request, self._timeout, self._LIMIT_CODES)
        results = records(data.get("results") if isinstance(data, dict) else None)
        return [self._hit(item) for item in results][:count]

    def _hit(self, item: dict[str, Any]) -> SearchHit:
        content = str(item.get("content") or "").strip()
        snippet = content if len(content) <= self._SNIPPET else f"{content[: self._SNIPPET]}…"
        return SearchHit(str(item.get("title") or ""), str(item.get("url") or ""), snippet, str(item.get("published_date") or ""))
