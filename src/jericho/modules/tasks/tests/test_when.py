from datetime import UTC, datetime, timedelta, timezone

import pytest

from jericho.modules.tasks.tests.fakes import START
from jericho.modules.tasks.when import duration, spoken_at


@pytest.mark.parametrize(
    ("later", "spoken"),
    [
        (timedelta(minutes=30), "сегодня, ср 21 октября, 20:30 (через 30 мин)"),
        (timedelta(hours=13), "завтра, чт 22 октября, 09:00 (через 13 ч)"),
        (timedelta(days=2, hours=1), "послезавтра, пт 23 октября, 21:00 (через 2 дн 1 ч)"),
        (timedelta(days=80), "сб 9 января 2027, 20:00 (через 80 дн)"),
    ],
)
def test_time_is_spoken_relative_to_now(later: timedelta, spoken: str) -> None:
    assert spoken_at(START + later, START) == spoken


NIGHT = datetime(2026, 10, 26, 0, 5, tzinfo=timezone(timedelta(hours=1)))     # 00:05 понедельника


@pytest.mark.parametrize(
    ("at", "spoken"),
    [
        (NIGHT.replace(hour=9, minute=0), "завтра, пн 26 октября, 09:00"),
        (NIGHT.replace(day=27, hour=9, minute=0), "послезавтра, вт 27 октября, 09:00"),
        (NIGHT.replace(hour=3, minute=0), "этой ночью, пн 26 октября, 03:00"),
    ],
)
def test_at_night_tomorrow_is_the_coming_morning(at: datetime, spoken: str) -> None:
    """Журнал 26.10.2026: «завтра в 9» в 00:05 ушло на вторник, а вопрос «завтра, вт 27 октября» это скрыл."""
    assert spoken_at(at, NIGHT).startswith(spoken)


def test_time_is_spoken_in_the_zone_of_the_user() -> None:
    assert spoken_at(datetime(2026, 10, 22, 7, 0, tzinfo=UTC), START).startswith("завтра, чт 22 октября, 09:00")


@pytest.mark.parametrize(
    ("delta", "spoken"),
    [(timedelta(seconds=20), "меньше минуты"), (timedelta(minutes=1, seconds=50), "2 мин"), (timedelta(hours=2), "2 ч"), (timedelta(hours=1, minutes=5), "1 ч 5 мин"), (timedelta(days=3), "3 дн")],
)
def test_duration(delta: timedelta, spoken: str) -> None:
    assert duration(delta) == spoken
