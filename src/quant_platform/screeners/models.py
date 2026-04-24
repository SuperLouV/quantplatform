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
