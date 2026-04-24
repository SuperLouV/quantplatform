"""Trading signal models shared by indicators, reports, UI, and backtests."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal


SignalDirection = Literal["long", "short", "neutral"]


@dataclass(slots=True)
class Signal:
    symbol: str
    signal_type: str
    direction: SignalDirection
    strength: int
    triggered_at: datetime
    price: float | None
    details: str
    indicator_values: dict[str, float | None] = field(default_factory=dict)


@dataclass(slots=True)
class SignalSummary:
    symbol: str
    as_of: datetime | None
    signals: list[Signal] = field(default_factory=list)
    long_score: int = 0
    short_score: int = 0
    net_score: int = 0

    @classmethod
    def from_signals(cls, symbol: str, as_of: datetime | None, signals: list[Signal]) -> "SignalSummary":
        long_score = sum(signal.strength for signal in signals if signal.direction == "long")
        short_score = sum(signal.strength for signal in signals if signal.direction == "short")
        return cls(
            symbol=symbol,
            as_of=as_of,
            signals=signals,
            long_score=long_score,
            short_score=short_score,
            net_score=long_score - short_score,
        )
