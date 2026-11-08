"""Настройки модуля «планы»."""

from __future__ import annotations

from jericho.core.conf.settings import SettingsSection


class PlansSettings(SettingsSection):
    # План сохраняется после «да» на показанный список: шаги часто собраны со страницы, а живут дольше фразы.
    # False — сразу, без вопроса: так решает владелец ассистента, который доверяет своим источникам.
    confirm_create: bool = True
