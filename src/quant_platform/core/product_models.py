"""Product-facing models for pools, snapshots, and AI analysis."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class StockPoolMember:
    symbol: str
    sources: list[str] = field(default_factory=list)
    themes: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    status: str = "candidate"
    reasons: list[str] = field(default_factory=list)


@dataclass(slots=True)
class StockPoolSnapshot:
    pool_id: str
    name: str
    pool_type: str
    source: str
    market: str
    symbols: list[str]
    members: list[StockPoolMember]
    updated_at: datetime
    notes: str | None = None


@dataclass(slots=True)
class StockSnapshot:
    symbol: str
    pool_ids: list[str] = field(default_factory=list)
    company_name: str | None = None
    sector: str | None = None
    industry: str | None = None
    currency: str | None = None
    open_price: float | None = None
    high_price: float | None = None
    low_price: float | None = None
    latest_close: float | None = None
    current_price: float | None = None
    regular_market_price: float | None = None
    pre_market_price: float | None = None
    post_market_price: float | None = None
    market_state: str | None = None
    previous_close: float | None = None
    change_percent: float | None = None
    latest_volume: float | None = None
    market_cap: float | None = None
    avg_dollar_volume: float | None = None
    trailing_pe: float | None = None
    forward_pe: float | None = None
    next_earnings_date: str | None = None
    exchange: str | None = None
    indicators: dict[str, float | str | None] = field(default_factory=dict)
    events: list[dict[str, str]] = field(default_factory=list)
    screening_status: str = "pending_data"
    screening_reasons: list[str] = field(default_factory=list)
    as_of: datetime | None = None


@dataclass(slots=True)
class AIAnalysisResult:
    analysis_id: str
    target_type: str
    target_id: str
    risk_level: str
    recommendation: str
    summary: str
    key_points: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    generated_at: datetime | None = None
