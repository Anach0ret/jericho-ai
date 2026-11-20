"""Настройки фоновых работ и их продолжений (`then`) — раздел `jobs`."""

from __future__ import annotations

from pydantic import Field

from jericho.core.conf.settings import SettingsSection


class JobsSettings(SettingsSection):
    # Строка `{{jobs}}`: работы, начатые за столько часов, и не больше стольких — промпт не растёт от старых дел.
    # Более давние модель найдёт в журнале (`read_journal`, kind="jobs").
    shown_hours: int = Field(default=6, ge=1, le=48)
    shown: int = Field(default=5, ge=1, le=20)
    # Продолжение после работы идёт само, только пока от просьбы прошло не больше стольких часов (владелец 12.11.2026:
    # 2 ч); позже — уведомление «выполнить сейчас?» и ручка `job_continue` с «да». Запись хранится `keep` часов.
    continuation_auto_hours: int = Field(default=2, ge=1, le=24)
    continuation_keep_hours: int = Field(default=24, ge=1, le=168)
    # Цепочка «сделай, потом, потом…»: звеньев вглубь и всего звеньев от одной просьбы (владелец: 5, «почему только три?»).
    chain_depth: int = Field(default=5, ge=1, le=10)
    chain_links: int = Field(default=10, ge=1, le=50)
    # Ассистент занят другой фразой — продолжение ждёт и пробует снова, потом приходит вопросом.
    busy_retries: int = Field(default=3, ge=0, le=10)
    busy_wait_seconds: int = Field(default=30, ge=1, le=600)
