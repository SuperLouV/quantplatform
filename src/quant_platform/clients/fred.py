"""FRED release calendar client."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, time
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from quant_platform.clients.base import BaseDataClient
from quant_platform.clients.protection import ProviderRequestGuard, ProviderRequestPolicy
from quant_platform.config import DataConfig
from quant_platform.core.market_events import MarketEvent
from quant_platform.core.models import Bar, DataRequest, Security, TradingCalendarEvent


FRED_API_BASE = "https://api.stlouisfed.org/fred"
EASTERN = ZoneInfo("America/New_York")

FRED_RELEASES = {
    9: ("零售销售", "consumer", "high", ["SPY", "QQQ", "XLY", "TLT"]),
    10: ("CPI 通胀", "inflation", "high", ["SPY", "QQQ", "TLT", "GLD", "DXY"]),
    46: ("PPI 通胀", "inflation", "medium", ["SPY", "QQQ", "TLT", "DXY"]),
    50: ("非农就业", "labor", "high", ["SPY", "QQQ", "TLT", "DXY"]),
    53: ("GDP", "growth", "high", ["SPY", "QQQ", "TLT"]),
    54: ("个人收入与 PCE", "inflation", "high", ["SPY", "QQQ", "TLT", "DXY"]),
}


class FredClient(BaseDataClient):
    provider_name = "fred"

    def __init__(self, api_key: str = "", user_agent: str = "quant-platform/0.1", policy: ProviderRequestPolicy | None = None) -> None:
        self.api_key = api_key
        self.user_agent = user_agent
        self.guard = ProviderRequestGuard(policy)

    @classmethod
    def from_data_config(cls, config: DataConfig) -> "FredClient":
        return cls(
            api_key=config.fred_api_key,
            user_agent=config.user_agent,
            policy=ProviderRequestPolicy(
                min_interval_seconds=config.request_min_interval_seconds,
                max_retries=config.request_max_retries,
                backoff_seconds=config.request_backoff_seconds,
                timeout_seconds=config.request_timeout_seconds,
            ),
        )

    def fetch_bars(self, request: DataRequest) -> list[Bar]:
        raise NotImplementedError("FRED client is for macro series, not equity bars.")

    def fetch_security(self, symbol: str) -> Security | None:
        raise NotImplementedError("FRED client does not provide equity metadata.")

    def fetch_events(self, symbol: str) -> list[TradingCalendarEvent]:
        raise NotImplementedError("FRED client does not provide corporate events.")

    def fetch_release_events(self, *, start: date, end: date) -> list[MarketEvent]:
        if not self.api_key:
            return []
        return self.guard.call("fetch_fred_release_events", lambda: self._fetch_release_events(start=start, end=end))

    def _fetch_release_events(self, *, start: date, end: date) -> list[MarketEvent]:
        events: list[MarketEvent] = []
        for release_id, (title, category, importance, affected_assets) in FRED_RELEASES.items():
            payload = self._get_json(
                "release/dates",
                {
                    "release_id": release_id,
                    "realtime_start": start.isoformat(),
                    "realtime_end": end.isoformat(),
                    "include_release_dates_with_no_data": "true",
                    "sort_order": "asc",
                    "file_type": "json",
                },
            )
            for item in payload.get("release_dates", []):
                value = item.get("date")
                if not value:
                    continue
                event_date = datetime.fromisoformat(value).date()
                event_time = datetime.combine(event_date, time(8, 30), tzinfo=EASTERN).astimezone(UTC)
                events.append(
                    MarketEvent(
                        event_id=f"fred:{release_id}:{value}",
                        title=title,
                        category=category,
                        source=self.provider_name,
                        event_time=event_time,
                        importance=importance,  # type: ignore[arg-type]
                        affected_assets=affected_assets,
                        status="estimated" if item.get("release_last_updated") is None else "released",
                        detail=f"FRED release_id={release_id}",
                        url=f"https://fred.stlouisfed.org/release?rid={release_id}",
                    )
                )
        return events

    def _get_json(self, endpoint: str, params: dict[str, object]) -> dict[str, object]:
        query = urlencode({**params, "api_key": self.api_key})
        request = Request(f"{FRED_API_BASE}/{endpoint}?{query}", headers={"User-Agent": self.user_agent})
        with urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
