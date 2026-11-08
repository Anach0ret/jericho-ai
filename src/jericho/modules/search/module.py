"""Модуль ядра «поиск в интернете»: своя ручка поиска, видимая каркасу, — для любого бэкенда."""

from __future__ import annotations

import os
from collections.abc import Sequence
from typing import Any, ClassVar

from jericho.core.modules.config import ModuleConfig, ModuleServices
from jericho.core.tools.tool import Tool
from jericho.modules.search.adapters.brave import BraveSearch
from jericho.modules.search.adapters.offline import OfflineSearch
from jericho.modules.search.adapters.tavily import TavilySearch
from jericho.modules.search.key import SearchKey
from jericho.modules.search.protocols import SearchEngine
from jericho.modules.search.settings import SearchSettings
from jericho.modules.search.tool import WebSearch


class SearchModule(ModuleConfig):
    """Поисковик собирает фабрика `engine()` — другой (SearXNG, Tavily) проект подставляет, переопределив её."""

    name = "search"

    KEY_VARIABLES: ClassVar[dict[str, str]] = {"tavily": "TAVILY_API_KEY", "brave": "BRAVE_SEARCH_API_KEY", "offline": ""}
    KEY_FILE = "search_key"      # в папке файлов машины: от ручек `files` она закрыта

    def ready(self, services: ModuleServices) -> None:
        self.services = services
        self.settings = services.settings.section(self.name, SearchSettings)

    def engine(self) -> SearchEngine:
        """«Вхолостую» (`DryRun`, `Eval`) — всегда офлайн: проба не тратит квоту поисковика, даже если вариант
        унаследовал настоящего с ключом (ревью 02.11.2026, П3b №4)."""
        settings = self.settings
        if settings.provider == "offline" or self.services.core.dry_run:
            return OfflineSearch()
        variable = settings.api_key_env or self.KEY_VARIABLES[settings.provider]
        key = SearchKey(variable, settings.api_key_file or self.services.program.config_dir / self.KEY_FILE, os.environ)
        if settings.provider == "brave":
            return BraveSearch(key, settings.country, settings.language, settings.timeout)
        return TavilySearch(key, settings.country, settings.timeout)

    def tools(self) -> Sequence[Tool[Any]]:
        return (WebSearch(self.engine(), self.services.core.foreign),)
