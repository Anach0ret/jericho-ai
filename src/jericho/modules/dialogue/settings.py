"""Настройки модуля «диалог»."""

from __future__ import annotations

from pydantic import Field

from jericho.core.conf.settings import SettingsSection


class DialogueSettings(SettingsSection):
    # Сколько помнится разговор: следующая фраза в этот срок — продолжение. Голосом за столом хватает пары минут;
    # долгая работа с паузами (тест, подтверждение в браузере) — дольше. Длиннее — больше риск принять новую
    # команду за ответ на старый вопрос.
    minutes: int = Field(default=2, ge=1, le=120)
