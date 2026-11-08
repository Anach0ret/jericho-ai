"""Настройки модуля «задачи»."""

from __future__ import annotations

import re
from typing import ClassVar, Literal, Self

from pydantic import Field, field_validator, model_validator

from jericho.core.conf.settings import OutputSettings, SettingsSection


class ScheduledTask(SettingsSection):
    """Одна задача: поручение, которое ассистент выполнит без человека рядом."""

    text: str = Field(min_length=1)        # поручение, как его сказал бы пользователь
    output: OutputSettings | None = None   # куда ответ; не задано — туда же, куда ответы проекта (раздел `output`)
    # Когда запускать. Формат — по `scheduler` раздела: календарь systemd («*-*-* 08:00», «Mon..Fri 09:30») или
    # cron («0 8 * * *», «30 9 * * 1-5», «@hourly»). Пусто — задача запускается только командой.
    schedule: str = ""


class ScheduledCommand(SettingsSection):
    """Команда проекта по расписанию — без модели: проверка порогов, уборка, выгрузка. Запускается без человека рядом."""

    command: tuple[str, ...] = Field(min_length=1)    # аргументы команды проекта: («watch»,) — это `<проект> watch`
    schedule: str = Field(min_length=1)               # формат — по `scheduler`, как у задач


class DeferredSettings(SettingsSection):
    """Отложенные поручения: «завтра в 9:00 сделай …», «через полчаса напомни …» — ставит модель ручкой `schedule`.

    В срок их исполняет команда `<проект> due`; её раз в минуту зовёт тик, который ставит `timers install`
    (или строка из `timers crontab`).
    """

    enabled: bool = False
    grace_minutes: int = Field(default=120, ge=0)     # поручение `do`, опоздавшее больше, не выполняется: машина спала
    keep_days: int = Field(default=7, ge=0)           # сколько хранить исполненные — чтобы спросить «что ты сделал утром?»
    max_pending: int = Field(default=50, ge=1)        # сколько может ждать одновременно
    horizon_days: int = Field(default=366, ge=1)      # дальше этого срока не ставится
    output: OutputSettings | None = None              # куда напоминания и итоги; не задано — туда же, куда ответы проекта


class TasksSettings(SettingsSection):
    """Задачи проекта по именам: `<проект> task <имя>`. Когда запускать, решает таймер машины, а не ассистент."""

    items: dict[str, ScheduledTask] = Field(default_factory=dict)
    commands: dict[str, ScheduledCommand] = Field(default_factory=dict)     # команды проекта по расписанию, без модели
    # Где живёт расписание. systemd — пользовательские таймеры (`timers install`): ПК и сервер без контейнера.
    # cron — файл для supercronic внутри контейнера (`timers crontab`): в Docker systemd нет.
    scheduler: Literal["systemd", "cron"] = "systemd"
    deferred: DeferredSettings = DeferredSettings()

    NAME: ClassVar[re.Pattern[str]] = re.compile(r"[a-z][a-z0-9_-]*")
    CRON: ClassVar[re.Pattern[str]] = re.compile(
        r"@(yearly|annually|monthly|weekly|daily|midnight|hourly)|[0-9A-Za-z*/,?-]+( [0-9A-Za-z*/,?-]+){4,6}"
    )

    @field_validator("items", "commands")
    @classmethod
    def _names_fit_the_command_line[EntryT](cls, items: dict[str, EntryT]) -> dict[str, EntryT]:
        wrong = [name for name in items if not cls.NAME.fullmatch(name)]
        if wrong:
            raise ValueError(f"task names must be lowercase latin, digits, '-' or '_': {', '.join(wrong)}")
        return items

    @model_validator(mode="after")
    def _cron_schedules_look_like_cron(self) -> Self:
        """Календарь systemd проверяет `systemd-analyze` при установке; cron — здесь: в контейнере проверить нечем."""
        if self.scheduler == "cron":
            schedules = {**{name: task.schedule for name, task in self.items.items()}, **{name: command.schedule for name, command in self.commands.items()}}
            wrong = [f"{name}: «{schedule}»" for name, schedule in schedules.items() if schedule and not self.CRON.fullmatch(schedule)]
            if wrong:
                raise ValueError(f"scheduler is cron, but schedule is not a cron expression — {'; '.join(wrong)}")
        return self
