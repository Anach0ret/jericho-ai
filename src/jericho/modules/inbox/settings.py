"""Настройки модуля «входящие»."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, field_validator

from jericho.core.assembly.installation import Installation
from jericho.core.conf.settings import SettingsSection
from jericho.core.conf.types import ExpandedPath


class InboxSettings(SettingsSection):
    """Раздел `inbox`. Пользователей нет — модуль не принимает ни одного сообщения: доступ открывается явно."""

    directory: ExpandedPath = Path("~/exchange")     # общая с транспортом папка: в ней ящики inbox/ и outbox/
    users: dict[str, str] = Field(default_factory=dict)    # кто может писать: идентификатор у транспорта → имя для журнала
    poll_seconds: float = Field(default=1.0, gt=0, le=60)   # как часто смотреть в ящик
    max_text: int = Field(default=4000, ge=1)                # длиннее — не поручение, а ошибка или поток
    answer_margin: float = Field(default=30.0, ge=0)          # сколько ждать ответа сверх срока фразы (agent.timeout)
    # Вопрос «да?» затянулся — напомнить один раз через столько минут (с кнопками «Да/Нет»); 0 — не напоминать.
    # Сам срок вопроса — `confirmation_minutes` в общих настройках; истёк — транспорту уходит «истёк, ничего не сделано».
    remind_minutes: int = Field(default=0, ge=0)

    @field_validator("users")
    @classmethod
    def _ids_fit_a_folder_name(cls, users: dict[str, str]) -> dict[str, str]:
        """Идентификатор становится именем папки сеанса пользователя (`JERICHO_USER`)."""
        wrong = [user for user in users if not Installation.USER_PATTERN.fullmatch(user)]
        if wrong:
            raise ValueError(f"inbox user ids: latin letters, digits, '-' and '_' only: {', '.join(wrong)}")
        return users
