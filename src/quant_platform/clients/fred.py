"""FRED client placeholder."""

from __future__ import annotations

from quant_platform.clients.base import BaseDataClient
from quant_platform.core.models import Bar, DataRequest, Security, TradingCalendarEvent


class FredClient(BaseDataClient):
    provider_name = "fred"

    def fetch_bars(self, request: DataRequest) -> list[Bar]:
        raise NotImplementedError("FRED client is for macro series, not equity bars.")

    def fetch_security(self, symbol: str) -> Security | None:
        raise NotImplementedError("FRED client does not provide equity metadata.")

    def fetch_events(self, symbol: str) -> list[TradingCalendarEvent]:
        raise NotImplementedError("FRED client does not provide corporate events.")
