"""SEC EDGAR client placeholder."""

from __future__ import annotations

from quant_platform.clients.base import BaseDataClient
from quant_platform.core.models import Bar, DataRequest, Security, TradingCalendarEvent


class SecClient(BaseDataClient):
    provider_name = "sec"

    def fetch_bars(self, request: DataRequest) -> list[Bar]:
        raise NotImplementedError("SEC client does not provide market bars.")

    def fetch_security(self, symbol: str) -> Security | None:
        raise NotImplementedError("SEC client is not implemented yet.")

    def fetch_events(self, symbol: str) -> list[TradingCalendarEvent]:
        raise NotImplementedError("SEC client is not implemented yet.")
