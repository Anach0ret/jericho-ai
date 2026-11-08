"""Сеть для адаптеров поиска — стандартный `urllib.request`; в тестах подменяется функцией с той же подписью."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable, Collection
from typing import Any, cast

from jericho.modules.search.errors import LimitReached, NotConfigured, SearchError

type Fetch = Callable[[urllib.request.Request, float], bytes]


def fetch_url(request: urllib.request.Request, timeout: float) -> bytes:
    with urllib.request.urlopen(request, timeout=timeout) as response:  # адрес задан в коде, https
        return cast(bytes, response.read())


def request_json(fetch: Fetch, request: urllib.request.Request, timeout: float, limit_codes: Collection[int] = (429,)) -> Any:
    """Ответ поисковика как JSON. Сбой — наследник `SearchError`: ключ не принят, лимит исчерпан или нет ответа.

    `limit_codes` — коды HTTP, которыми поисковик говорит «лимит исчерпан»: у каждого свои.
    """
    try:
        body = fetch(request, timeout)
    except urllib.error.HTTPError as error:
        if error.code in (401, 403):
            raise NotConfigured(f"поисковик не принял ключ (HTTP {error.code})") from error
        if error.code in limit_codes:
            raise LimitReached("исчерпан лимит запросов поисковика") from error
        raise SearchError(f"поисковик ответил HTTP {error.code}") from error
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise SearchError(f"поисковик не ответил: {error}") from error
    try:
        return json.loads(body)
    except ValueError as error:
        raise SearchError("поисковик прислал не JSON") from error


def records(value: object) -> list[dict[str, Any]]:
    """Список словарей из ответа; всё, что не словарь, пропускается: ответ пришёл снаружи."""
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []  # pyright: ignore[reportUnknownVariableType]
