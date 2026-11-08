"""Настройки модуля «голос»."""

from __future__ import annotations

from pathlib import Path

from jericho.core.conf.settings import SettingsSection
from jericho.core.conf.types import ExpandedPath


class VoiceSettings(SettingsSection):
    """Распознавание речи. Проект объявляет раздел `voice` у себя, если хочет менять значения."""

    title: str = ""                         # заголовок уведомлений; пусто — имя проекта
    icon: str = ""                          # значок уведомлений: имя из темы значков или путь; пусто — решает панель
    buttons: bool = True                    # вопрос с «да» — с кнопками «Да» и «Нет» в уведомлении
    answer_wait: float = 120.0              # секунд ждать нажатия; столько же живёт вопрос (ConfirmationFile.ttl)
    reply_field: bool = True                # уточняющий вопрос модели — с полем для ответа текстом в уведомлении
    recognizer: str = "hyprwhspr"           # чем распознавать: имя адаптера из списка модуля
    hyprwhspr: ExpandedPath = Path("hyprwhspr")
    listen_timeout: float = 60.0            # секунд на одну фразу: дольше — запись отменяется
