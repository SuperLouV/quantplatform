"""Project timezone helpers.

Local operation timestamps use Beijing time. Market-date calculations for US
stocks are explicit and use America/New_York.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from quant_platform.market_calendar import (
    is_us_market_session,
    latest_completed_us_session,
    previous_us_market_session,
)

BEIJING = ZoneInfo("Asia/Shanghai")
US_EASTERN = ZoneInfo("America/New_York")


def now_beijing() -> datetime:
    return datetime.now(tz=BEIJING)


def now_us_eastern() -> datetime:
    return datetime.now(tz=US_EASTERN)


def to_beijing(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=BEIJING)
    return value.astimezone(BEIJING)


def to_us_eastern(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=US_EASTERN)
    return value.astimezone(US_EASTERN)


def iso_beijing(value: datetime | None = None) -> str:
    return to_beijing(value or now_beijing()).isoformat()


def latest_us_weekday(reference: datetime | None = None) -> date:
    current = to_us_eastern(reference or now_us_eastern()).date()
    while not is_us_market_session(current):
        current -= timedelta(days=1)
    return current


def latest_expected_us_market_data_date(reference: datetime | None = None) -> date:
    current_time = to_us_eastern(reference or now_us_eastern())
    current = current_time.date()
    if not is_us_market_session(current):
        return latest_us_weekday(current_time)
    if current_time.time() < time(9, 30):
        current = previous_us_market_session(current)
    return current


def latest_completed_us_market_date(reference: datetime | None = None) -> date:
    return latest_completed_us_session(to_us_eastern(reference or now_us_eastern()))
