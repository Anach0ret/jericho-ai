"""Порт поиска: запрос — выдержки со ссылками. Какой поисковик за ним, ручке всё равно."""

from __future__ import annotations

from typing import Protocol

from jericho.modules.search.entities import Freshness, SearchHit


class SearchEngine(Protocol):
    def search(self, query: str, count: int, freshness: Freshness) -> list[SearchHit]:
        """Ошибки — наследники `SearchError`."""
        ...
