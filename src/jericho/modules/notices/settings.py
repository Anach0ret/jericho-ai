"""Настройки модуля «уведомления»."""

from __future__ import annotations

import re

from pydantic import Field, field_validator

from jericho.core.conf.settings import SettingsSection

_NAME = re.compile(r"[A-Za-z0-9_-]{1,64}")


class NoticesSettings(SettingsSection):
    """Раздел `notices`. Адресат вывода в ящик (`OutputSettings.to`, «owner») → чей это разговор (`JERICHO_USER`,
    у серверного — Telegram ID). Не названный здесь адресат ничьим не считается: его уведомлений модель не увидит."""

    recipients: dict[str, str] = Field(default_factory=dict)
    shown: int = Field(default=5, ge=1, le=20)        # сколько последних уведомлений показать, когда ответ не reply
    chars: int = Field(default=800, ge=100, le=4000)  # сколько текста уведомления показать модели

    @field_validator("recipients")
    @classmethod
    def _names(cls, recipients: dict[str, str]) -> dict[str, str]:
        wrong = [to for to in recipients if not _NAME.fullmatch(to)]
        if wrong:
            raise ValueError(f"notices recipients: 'to' names are latin letters, digits, '-' and '_': {', '.join(wrong)}")
        return recipients
