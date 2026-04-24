"""Canonical data models shared across providers and pipelines."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any


@dataclass(slots=True)
class DataRequest:
    symbol: str
    start: date | datetime | None = None
    end: date | datetime | None = None
    interval: str = "1d"
    adjusted: bool = True


@dataclass(slots=True)
class Bar:
    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    provider: str
    adjusted: bool = True


@dataclass(slots=True)
class Security:
    symbol: str
    name: str | None = None
    exchange: str | None = None
    sector: str | None = None
    industry: str | None = None
    market_cap: float | None = None
    currency: str | None = None
    extra: dict[str, Any] | None = None


@dataclass(slots=True)
class FundamentalsSnapshot:
    symbol: str
    as_of_date: date | None = None
    market_cap: float | None = None
    shares_outstanding: float | None = None
    pe_ratio: float | None = None
    dividend_yield: float | None = None
    extra: dict[str, Any] | None = None


@dataclass(slots=True)
class TradingCalendarEvent:
    symbol: str
    event_type: str
    event_date: date
    provider: str
    detail: str | None = None
