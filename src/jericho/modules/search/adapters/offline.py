"""Поиск без сети — для прогонов и проб: запросы к платному или ограниченному поисковику не тратятся."""

from __future__ import annotations

import urllib.parse

from jericho.modules.search.entities import Freshness, SearchHit


class OfflineSearch:
    """Отвечает одной выдуманной выдержкой. Ручка ведёт себя как с настоящим поиском: найденное — чужой текст."""

    def search(self, query: str, count: int, freshness: Freshness) -> list[SearchHit]:
        return [SearchHit(
            title=f"Поиск вхолостую: {query}",
            url=f"https://example.invalid/search?{urllib.parse.urlencode({'q': query})}",
            snippet="Настоящего поиска не было: в этом варианте настроек поиск отключён, чтобы не тратить запросы.",
        )]
