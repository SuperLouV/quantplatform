"""Federal Reserve public calendar client."""

from __future__ import annotations

from datetime import UTC, datetime, time
from html.parser import HTMLParser
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from quant_platform.clients.protection import ProviderRequestGuard, ProviderRequestPolicy
from quant_platform.config import DataConfig
from quant_platform.core.market_events import MarketEvent


FOMC_CALENDAR_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
EASTERN = ZoneInfo("America/New_York")

_FALLBACK_FOMC_DATES = {
    2026: ["2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17", "2026-07-29", "2026-09-16", "2026-10-28", "2026-12-09"],
    2027: ["2027-01-27", "2027-03-17", "2027-04-28", "2027-06-09", "2027-07-28", "2027-09-15", "2027-10-27", "2027-12-08"],
}


class FedCalendarClient:
    provider_name = "fed"

    def __init__(self, user_agent: str, policy: ProviderRequestPolicy | None = None) -> None:
        self.user_agent = user_agent
        self.guard = ProviderRequestGuard(policy)

    @classmethod
    def from_data_config(cls, config: DataConfig) -> "FedCalendarClient":
        return cls(
            user_agent=config.user_agent,
            policy=ProviderRequestPolicy(
                min_interval_seconds=config.request_min_interval_seconds,
                max_retries=config.request_max_retries,
                backoff_seconds=config.request_backoff_seconds,
                timeout_seconds=config.request_timeout_seconds,
            ),
        )

    def fetch_fomc_events(self, years: list[int]) -> list[MarketEvent]:
        return self.guard.call("fetch_fomc_events", lambda: self._fetch_fomc_events(years))

    def _fetch_fomc_events(self, years: list[int]) -> list[MarketEvent]:
        html = _fetch_text(FOMC_CALENDAR_URL, user_agent=self.user_agent)
        text = _visible_text(html)
        parsed_dates = _parse_fomc_dates(text, years)
        if not parsed_dates:
            parsed_dates = {year: _FALLBACK_FOMC_DATES.get(year, []) for year in years}

        events: list[MarketEvent] = []
        for year, dates in parsed_dates.items():
            for value in dates:
                event_date = datetime.fromisoformat(value).date()
                event_time = datetime.combine(event_date, time(14, 0), tzinfo=EASTERN).astimezone(UTC)
                events.append(
                    MarketEvent(
                        event_id=f"fed:fomc:{value}",
                        title="FOMC 利率决议",
                        category="fomc",
                        source=self.provider_name,
                        event_time=event_time,
                        importance="high",
                        affected_assets=["SPY", "QQQ", "TLT", "DXY", "GLD"],
                        detail="美联储议息会议结束日。通常 14:00 ET 公布声明，部分会议含经济预测和发布会。",
                        url=FOMC_CALENDAR_URL,
                    )
                )
        return events


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        value = " ".join(data.split())
        if value:
            self.parts.append(value)


def _fetch_text(url: str, *, user_agent: str) -> str:
    request = Request(url, headers={"User-Agent": user_agent})
    with urlopen(request, timeout=20) as response:
        return response.read().decode("utf-8", errors="replace")


def _visible_text(html: str) -> list[str]:
    parser = _TextExtractor()
    parser.feed(html)
    return parser.parts


def _parse_fomc_dates(parts: list[str], years: list[int]) -> dict[int, list[str]]:
    month_numbers = {
        "January": 1,
        "March": 3,
        "April": 4,
        "June": 6,
        "July": 7,
        "September": 9,
        "October": 10,
        "December": 12,
    }
    result: dict[int, list[str]] = {year: [] for year in years}
    active_year: int | None = None
    active_month: int | None = None

    for part in parts:
        for year in years:
            if part == f"{year} FOMC Meetings":
                active_year = year
                active_month = None
                break
        else:
            if active_year is None:
                continue
            if part.endswith("FOMC Meetings") and not any(part == f"{year} FOMC Meetings" for year in years):
                active_year = None
                active_month = None
                continue
            if part in month_numbers:
                active_month = month_numbers[part]
                continue
            if active_month and _looks_like_day_range(part):
                day = int(part.replace("*", "").split("-")[-1])
                result[active_year].append(f"{active_year:04d}-{active_month:02d}-{day:02d}")

    return {year: dates for year, dates in result.items() if dates}


def _looks_like_day_range(value: str) -> bool:
    cleaned = value.replace("*", "")
    return cleaned.replace("-", "").isdigit() and 1 <= len(cleaned) <= 5
