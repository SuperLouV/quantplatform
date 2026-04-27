"""Models for candidate sourcing, universe construction, and screening decisions."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class ScreeningSnapshot:
    symbol: str
    price: float | None = None
    market_cap: float | None = None
    avg_dollar_volume: float | None = None
    listing_months: int | None = None
    exchange: str | None = None


@dataclass(slots=True)
class UniverseCandidate:
    symbol: str
    sources: set[str] = field(default_factory=set)
    themes: set[str] = field(default_factory=set)
    tags: set[str] = field(default_factory=set)

    def add_source(self, source: str) -> None:
        self.sources.add(source)


@dataclass(slots=True)
class ScreeningDecision:
    symbol: str
    passed: bool
    status: str
    reasons: list[str] = field(default_factory=list)


@dataclass(slots=True)
class UniverseBuildResult:
    theme_pool: list[UniverseCandidate]
    system_pool: list[UniverseCandidate]
    watchlist: list[UniverseCandidate]
    tradable_universe: list[UniverseCandidate]
    decisions: list[ScreeningDecision]


@dataclass(slots=True)
class ScanSignal:
    signal_type: str
    direction: str
    strength: int
    state: str
    reason: str
    evidence: dict[str, float | str | None] = field(default_factory=dict)


@dataclass(slots=True)
class ScanCandidate:
    strategy_id: str
    symbol: str
    company_name: str | None
    price: float | None
    change_percent: float | None
    latest_history_date_us: str | None
    snapshot_refreshed_at_beijing: str | None
    score: int
    action: str
    risk_level: str
    trend_state: str
    rsi_state: str
    macd_state: str
    volume_state: str
    data_quality: str
    momentum_rank_pct: float | None = None
    confidence: int | None = None
    market_regime: str | None = None
    signals: list[ScanSignal] = field(default_factory=list)

    @property
    def reasons(self) -> list[str]:
        return [signal.reason for signal in self.signals if signal.reason]


@dataclass(slots=True)
class ScanSummary:
    total: int
    candidate_buy: int
    watch: int
    risk_avoid: int
    insufficient_data: int
    high_risk: int
    medium_risk: int
    low_risk: int


@dataclass(slots=True)
class ScanResult:
    summary: ScanSummary
    candidates: list[ScanCandidate]
