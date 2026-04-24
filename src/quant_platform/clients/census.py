"""U.S. Census economic indicator calendar client."""

from __future__ import annotations

from datetime import UTC, datetime
from html.parser import HTMLParser
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from quant_platform.clients.protection import ProviderRequestGuard, ProviderRequestPolicy
from quant_platform.config import DataConfig
from quant_platform.core.market_events import MarketEvent


CENSUS_CALENDAR_URL = "https://www.census.gov/economic-indicators/calendar-listview.html"
EASTERN = ZoneInfo("America/New_York")


class CensusCalendarClient:
    provider_name = "census"

    def __init__(self, user_agent: str, policy: ProviderRequestPolicy | None = None) -> None:
        self.user_agent = user_agent
        self.guard = ProviderRequestGuard(policy)

    @classmethod
    def from_data_config(cls, config: DataConfig) -> "CensusCalendarClient":
        return cls(
            user_agent=config.user_agent,
            policy=ProviderRequestPolicy(
                min_interval_seconds=config.request_min_interval_seconds,
                max_retries=config.request_max_retries,
                backoff_seconds=config.request_backoff_seconds,
                timeout_seconds=config.request_timeout_seconds,
            ),
        )

    def fetch_events(self) -> list[MarketEvent]:
        return self.guard.call("fetch_census_calendar", self._fetch_events)

    def _fetch_events(self) -> list[MarketEvent]:
        html = _fetch_text(CENSUS_CALENDAR_URL, user_agent=self.user_agent)
        rows = _CalendarTableParser.parse(html)
        events: list[MarketEvent] = []
        for row in rows:
            if len(row) < 4:
                continue
            indicator, release_date, release_time, period = row[:4]
            if not _is_important_indicator(indicator):
                continue
            event_time = _parse_release_datetime(release_date, release_time)
            if event_time is None:
                continue
            events.append(
                MarketEvent(
                    event_id=f"census:{_slug(indicator)}:{event_time.date().isoformat()}",
                    title=_short_title(indicator),
                    category=_category(indicator),
                    source=self.provider_name,
                    event_time=event_time,
                    importance=_importance(indicator),
                    affected_assets=["SPY", "QQQ", "TLT", "XHB", "XLY"],
                    detail=f"{indicator}，覆盖期：{period}",
                    url=CENSUS_CALENDAR_URL,
                )
            )
        return events


class _CalendarTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_cell = False
        self.in_row = False
        self.current_cell: list[str] = []
        self.current_row: list[str] = []
        self.rows: list[list[str]] = []

    @classmethod
    def parse(cls, html: str) -> list[list[str]]:
        parser = cls()
        parser.feed(html)
        return parser.rows

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self.in_row = True
            self.current_row = []
        if tag in {"td", "th"} and self.in_row:
            self.in_cell = True
            self.current_cell = []

    def handle_data(self, data: str) -> None:
        if self.in_cell:
            value = " ".join(data.split())
            if value:
                self.current_cell.append(value)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self.in_cell:
            self.current_row.append(" ".join(self.current_cell).strip())
            self.in_cell = False
        if tag == "tr" and self.in_row:
            if self.current_row:
                self.rows.append(self.current_row)
            self.in_row = False


def _fetch_text(url: str, *, user_agent: str) -> str:
    request = Request(url, headers={"User-Agent": user_agent})
    with urlopen(request, timeout=20) as response:
        return response.read().decode("utf-8", errors="replace")


def _is_important_indicator(indicator: str) -> bool:
    names = (
        "Advance Monthly Sales",
        "New Residential Construction",
        "New Residential Sales",
        "Advance Report on Durable Goods",
        "U.S. International Trade",
        "Construction Spending",
        "Advance Economic Indicators",
    )
    return any(name in indicator for name in names)


def _parse_release_datetime(release_date: str, release_time: str) -> datetime | None:
    try:
        parsed = datetime.strptime(f"{release_date} {release_time}", "%B %d, %Y %I:%M %p")
    except ValueError:
        return None
    return parsed.replace(tzinfo=EASTERN).astimezone(UTC)


def _short_title(indicator: str) -> str:
    replacements = {
        "Advance Monthly Sales for Retail and Food Services": "零售销售",
        "New Residential Construction (Building Permits, Housing Starts, and Housing Completions)": "新屋开工 / 建筑许可",
        "New Residential Sales": "新屋销售",
        "Advance Report on Durable Goods--Manufacturers' Shipments, Inventories, and Orders": "耐用品订单",
        "U.S. International Trade in Goods and Services": "贸易帐",
        "Construction Spending (Construction Put in Place)": "建筑支出",
        "Advance Economic Indicators Report (International Trade, Retail, & Wholesale)": "提前经济指标",
    }
    return replacements.get(indicator, indicator)


def _category(indicator: str) -> str:
    if "Residential" in indicator or "Construction" in indicator:
        return "housing"
    if "Sales" in indicator or "Retail" in indicator:
        return "consumer"
    if "Trade" in indicator:
        return "trade"
    if "Durable" in indicator:
        return "manufacturing"
    return "growth"


def _importance(indicator: str) -> str:
    if "Advance Monthly Sales" in indicator or "Durable Goods" in indicator:
        return "high"
    return "medium"


def _slug(value: str) -> str:
    return "".join(char.lower() if char.isalnum() else "-" for char in value).strip("-")
