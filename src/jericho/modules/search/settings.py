"""Настройки модуля «поиск в интернете»."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from jericho.core.conf.settings import SettingsSection
from jericho.core.conf.types import ExpandedPath


class SearchSettings(SettingsSection):
    """Раздел `search`. Ключ в настройках не лежит: переменная окружения или файл, который читает только владелец."""

    # Поисковик. tavily — бесплатно 1000 запросов в месяц без карты; brave — платный ($5 за 1000);
    # offline — без сети, выдуманная выдержка: для прогонов `eval` и проб вхолостую, чтобы не тратить запросы
    provider: Literal["tavily", "brave", "offline"] = "tavily"
    api_key_env: str = ""       # пусто — по поисковику: TAVILY_API_KEY или BRAVE_SEARCH_API_KEY
    # Файл с ключом — для ассистента, которого запускает рабочий стол: переменную окружения ему не передать
    # без записи ключа в конфиг. Не задан — `search_key` в папке файлов машины (~/.config/<проект>): её ручки
    # `files` не трогают. Другое место — на совести проекта: от ручек его закрывает только `files.deny`.
    api_key_file: ExpandedPath | None = None
    country: str = Field(default="", max_length=40)    # brave — код «DE»; tavily — название «germany»; пусто — без привязки
    language: str = Field(default="", max_length=5)    # «ru», «en» — язык страниц (только brave); пусто — любой
    timeout: float = Field(default=10.0, gt=0, le=60)
