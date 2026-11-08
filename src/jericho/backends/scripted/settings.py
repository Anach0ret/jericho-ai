"""Настройки бэкенда «сценарий» — раздел `scripted`."""

from __future__ import annotations

from jericho.core.conf.settings import SettingsSection


class ScriptedSettings(SettingsSection):
    """Проект объявляет раздел у себя: `scripted: ScriptedSettings = ScriptedSettings(script="home.settings:script.yaml")`."""

    # Файл сценария: «пакет:путь внутри пакета». Пусто — сценария нет: на любое поручение бэкенд отвечает,
    # что он не модель, и ничего не вызывает.
    script: str = ""
