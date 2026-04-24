"""Base interfaces for external data providers."""

from __future__ import annotations

from abc import ABC, abstractmethod

from quant_platform.core.models import Bar, DataRequest, Security, TradingCalendarEvent


class BaseDataClient(ABC):
    """Stable boundary between provider code and internal pipelines."""

    provider_name: str

    @abstractmethod
    def fetch_bars(self, request: DataRequest) -> list[Bar]:
        raise NotImplementedError

    def fetch_security(self, symbol: str) -> Security | None:
        return None

    def fetch_events(self, symbol: str) -> list[TradingCalendarEvent]:
        return []
