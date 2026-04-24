"""Provider-agnostic ingestion entrypoints."""

from __future__ import annotations

from dataclasses import dataclass

from quant_platform.clients.base import BaseDataClient
from quant_platform.core.models import Bar, DataRequest, Security, TradingCalendarEvent


@dataclass(slots=True)
class DataIngestionPipeline:
    client: BaseDataClient

    def ingest_bars(self, request: DataRequest) -> list[Bar]:
        return self.client.fetch_bars(request)

    def ingest_security(self, symbol: str) -> Security | None:
        return self.client.fetch_security(symbol)

    def ingest_events(self, symbol: str) -> list[TradingCalendarEvent]:
        return self.client.fetch_events(symbol)
