"""Отказы поиска: слой `Refusals` превращает их в ответ модели."""

from __future__ import annotations

from jericho.core.errors import PortError


class SearchError(PortError):
    code = "search_failed"


class NotConfigured(SearchError):
    code = "search_not_configured"


class LimitReached(SearchError):
    code = "search_limit"
