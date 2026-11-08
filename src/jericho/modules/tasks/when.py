"""Срок словами — так, как его скажет код, а не модель: по этой строке пользователь проверяет, что поставлено."""

from __future__ import annotations

from datetime import datetime, timedelta

from jericho.core.services.calendar import MONTHS, WEEKDAYS_SHORT

# До этого часа человек ещё живёт вчерашним днём: в 00:05 понедельника «завтра» для него — утро понедельника.
NIGHT_END_HOUR = 5


def spoken_at(at: datetime, now: datetime) -> str:
    """«завтра, чт 22 октября, 09:00 (через 13 ч)» — время в поясе `now`, то есть пользователя.

    «Сегодня / завтра / послезавтра» ночью считаются от вчерашнего дня, как их слышит человек: срок на вторник,
    поставленный в 00:05 понедельника, звучит «послезавтра» — и неверно понятое «завтра» видно в вопросе
    (журнал 26.10.2026: «завтра в 9» ушло на вторник, а вопрос «завтра, вт 27 октября» это скрыл).
    """
    at = at.astimezone(now.tzinfo)
    night = now.hour < NIGHT_END_HOUR
    days = (at.date() - now.date()).days + (1 if night else 0)
    day = "этой ночью" if night and days == 1 and at.hour < NIGHT_END_HOUR else {0: "сегодня", 1: "завтра", 2: "послезавтра"}.get(days)
    date = f"{WEEKDAYS_SHORT[at.weekday()]} {at.day} {MONTHS[at.month - 1]}" + ("" if at.year == now.year else f" {at.year}")
    head = f"{day}, {date}" if day else date
    return f"{head}, {at:%H:%M} (через {duration(at - now)})"


def duration(delta: timedelta) -> str:
    """«2 дн 3 ч», «1 ч 20 мин», «5 мин» — с округлением до минуты: 1 мин 50 с — «2 мин», а не «1 мин»."""
    minutes = max(round(delta.total_seconds() / 60), 0)
    days, minutes = divmod(minutes, 24 * 60)
    hours, minutes = divmod(minutes, 60)
    if days:
        return f"{days} дн {hours} ч" if hours else f"{days} дн"
    if hours:
        return f"{hours} ч {minutes} мин" if minutes else f"{hours} ч"
    return f"{minutes} мин" if minutes else "меньше минуты"
