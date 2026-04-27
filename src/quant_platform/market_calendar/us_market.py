"""Local US equity market calendar.

This calendar covers common NYSE/Nasdaq regular holidays and recurring early
closes. It deliberately avoids external API calls so daily refresh can run
offline. One-off exchange closures can be added later through a reference file
or provider-backed calendar.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta


REGULAR_CLOSE = time(16, 0)
EARLY_CLOSE = time(13, 0)


def is_us_market_session(day: date) -> bool:
    return day.weekday() < 5 and not is_us_market_holiday(day)


def is_us_market_holiday(day: date) -> bool:
    return day in us_market_holidays(day.year)


def previous_us_market_session(day: date) -> date:
    current = day - timedelta(days=1)
    while not is_us_market_session(current):
        current -= timedelta(days=1)
    return current


def latest_completed_us_session(reference: datetime, *, data_delay_minutes: int = 90) -> date:
    current = reference.date()
    if not is_us_market_session(current):
        while not is_us_market_session(current):
            current -= timedelta(days=1)
        return current

    close_at = _datetime_at(reference, market_close_time(current)) + timedelta(minutes=data_delay_minutes)
    if reference < close_at:
        return previous_us_market_session(current)
    return current


def market_close_time(day: date) -> time:
    return EARLY_CLOSE if is_us_market_early_close(day) else REGULAR_CLOSE


def is_us_market_early_close(day: date) -> bool:
    if not is_us_market_session(day):
        return False
    thanksgiving = _nth_weekday(day.year, 11, 3, 4)
    if day == thanksgiving + timedelta(days=1):
        return True
    if day.month == 12 and day.day == 24 and day.weekday() < 5:
        return True
    if day.month == 7 and day.day == 3 and day.weekday() < 5:
        return True
    return False


def us_market_holidays(year: int) -> set[date]:
    holidays = {
        _observed_fixed_holiday(year, 1, 1),
        _nth_weekday(year, 1, 0, 3),
        _nth_weekday(year, 2, 0, 3),
        _good_friday(year),
        _last_weekday(year, 5, 0),
        _observed_fixed_holiday(year, 6, 19),
        _observed_fixed_holiday(year, 7, 4),
        _nth_weekday(year, 9, 0, 1),
        _nth_weekday(year, 11, 3, 4),
        _observed_fixed_holiday(year, 12, 25),
        _observed_fixed_holiday(year + 1, 1, 1),
    }
    if year < 2022:
        holidays.discard(_observed_fixed_holiday(year, 6, 19))
    return {day for day in holidays if day.year == year}


def _observed_fixed_holiday(year: int, month: int, day: int) -> date:
    actual = date(year, month, day)
    if actual.weekday() == 5:
        return actual - timedelta(days=1)
    if actual.weekday() == 6:
        return actual + timedelta(days=1)
    return actual


def _nth_weekday(year: int, month: int, weekday: int, nth: int) -> date:
    current = date(year, month, 1)
    while current.weekday() != weekday:
        current += timedelta(days=1)
    return current + timedelta(days=7 * (nth - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    if month == 12:
        current = date(year, 12, 31)
    else:
        current = date(year, month + 1, 1) - timedelta(days=1)
    while current.weekday() != weekday:
        current -= timedelta(days=1)
    return current


def _good_friday(year: int) -> date:
    return _easter_sunday(year) - timedelta(days=2)


def _easter_sunday(year: int) -> date:
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    leaping = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * leaping) // 451
    month = (h + leaping - 7 * m + 114) // 31
    day = ((h + leaping - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def _datetime_at(reference: datetime, value: time) -> datetime:
    return datetime.combine(reference.date(), value, tzinfo=reference.tzinfo)
