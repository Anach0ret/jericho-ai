"""Общее у разделов настроек бэкендов по ключу API: какая модель, где ключ, сколько ходов."""

from __future__ import annotations

from pydantic import Field

from jericho.core.conf.settings import SettingsSection
from jericho.core.conf.types import ExpandedPath


class ApiModelSettings(SettingsSection):
    """Наследник — раздел своего бэкенда: меняет умолчания и добавляет своё (адрес у протокола OpenAI)."""

    model: str = ""
    api_key_env: str = ""                          # имя переменной окружения с ключом; сам ключ в настройках не лежит
    # Файл с ключом — если переменной нет: ассистенту рабочего стола её не передать. Клади в папку файлов машины
    # (~/.config/<проект>): от ручек `files` она закрыта.
    api_key_file: ExpandedPath | None = None
    max_tokens: int = Field(default=2048, gt=0)    # на один ход модели
    max_turns: int = Field(default=12, gt=0)       # ходов на поручение: дальше — сбой, а не бесконечный цикл
