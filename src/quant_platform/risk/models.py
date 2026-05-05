"""Structured risk models for account-aware research reports."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any


@dataclass(slots=True)
class RiskPolicy:
    max_position_weight: float = 0.08
    max_sector_weight: float = 0.25
    max_open_positions: int = 12
    max_portfolio_drawdown: float = 0.12
    max_single_position_loss_pct: float = 0.02
    max_total_atr_risk_pct: float = 0.06
    atr_stop_multiplier: float = 2.0
    pdt_equity_threshold: float = 25_000
    pdt_day_trade_limit_5d: int = 3
    event_risk_window_days: int = 7
    min_cash_ratio: float = 0.10
    high_hhi_threshold: float = 0.18

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ATRStopAdvice:
    symbol: str
    reference_price: float | None
    atr_14: float | None
    stop_price: float | None
    stop_distance_pct: float | None
    estimated_loss: float | None
    estimated_loss_pct_of_equity: float | None
    status: str
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class PositionRisk:
    symbol: str
    name: str | None
    sector: str
    quantity: float
    cost_price: float | None
    current_price: float | None
    market_value: float | None
    weight_pct: float | None
    unrealized_pl: float | None
    unrealized_pl_pct: float | None
    concentration_status: str
    max_loss_status: str
    atr_stop: ATRStopAdvice
    flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["atr_stop"] = self.atr_stop.to_dict()
        return payload


@dataclass(slots=True)
class SectorExposure:
    sector: str
    market_value: float
    weight_pct: float
    position_count: int
    status: str
    symbols: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class PDTCheck:
    equity: float
    threshold: float
    day_trade_count_5d: int | None
    status: str
    message: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class EventRisk:
    event_type: str
    symbol: str | None
    title: str
    event_date: date | None
    importance: str
    source: str
    status: str

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["event_date"] = self.event_date.isoformat() if self.event_date else None
        return payload


@dataclass(slots=True)
class RiskAssessment:
    generated_at_beijing: str
    currency: str
    equity: float
    cash: float
    cash_ratio_pct: float | None
    invested_value: float
    position_count: int
    hhi: float
    health_score: int
    health_state: str
    pdt: PDTCheck
    positions: list[PositionRisk]
    sector_exposures: list[SectorExposure]
    event_risks: list[EventRisk]
    max_loss_checks: dict[str, Any]
    recommendations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at_beijing": self.generated_at_beijing,
            "currency": self.currency,
            "equity": round(self.equity, 2),
            "cash": round(self.cash, 2),
            "cash_ratio_pct": _round_optional(self.cash_ratio_pct),
            "invested_value": round(self.invested_value, 2),
            "position_count": self.position_count,
            "hhi": round(self.hhi, 4),
            "health_score": self.health_score,
            "health_state": self.health_state,
            "pdt": self.pdt.to_dict(),
            "positions": [item.to_dict() for item in self.positions],
            "sector_exposures": [item.to_dict() for item in self.sector_exposures],
            "event_risks": [item.to_dict() for item in self.event_risks],
            "max_loss_checks": self.max_loss_checks,
            "recommendations": self.recommendations,
            "warnings": self.warnings,
        }


def _round_optional(value: float | None) -> float | None:
    return None if value is None else round(value, 2)
