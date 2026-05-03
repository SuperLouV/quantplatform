"""Structured models for conservative options strategy analysis."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any, Literal


OptionType = Literal["put", "call"]
OptionStrategy = Literal["cash_secured_put", "covered_call"]
OptionDecision = Literal["符合策略", "继续观察", "不适合"]
OptionCandidateStatus = Literal["candidate", "watch", "blocked"]


@dataclass(slots=True)
class AccountProfile:
    equity: float = 5_000
    cash: float = 5_000
    max_cash_per_trade_pct: float = 0.4
    max_loss_pct: float = 0.5
    allow_assignment: bool = True
    stock_shares: int = 0
    stock_cost_basis: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class StockOptionContext:
    symbol: str
    current_price: float
    as_of: date
    support_price: float | None = None
    resistance_price: float | None = None
    trend_state: str | None = None
    rsi14: float | None = None
    earnings_days: int | None = None
    market_risk_state: str | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["as_of"] = self.as_of.isoformat()
        return payload


@dataclass(slots=True)
class OptionContract:
    symbol: str
    option_type: OptionType
    strike: float
    expiration: date
    bid: float
    ask: float
    delta: float | None = None
    implied_volatility: float | None = None
    volume: int | None = None
    open_interest: int | None = None

    @property
    def mid(self) -> float:
        if self.bid > 0 and self.ask > 0:
            return (self.bid + self.ask) / 2
        return max(self.bid, self.ask, 0)

    def dte(self, as_of: date) -> int:
        return max(0, (self.expiration - as_of).days)

    def spread_pct(self) -> float | None:
        mid = self.mid
        if mid <= 0:
            return None
        return (self.ask - self.bid) / mid

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["expiration"] = self.expiration.isoformat()
        payload["mid"] = self.mid
        payload["spread_pct"] = self.spread_pct()
        return payload


@dataclass(slots=True)
class OptionStrategyRequest:
    strategy: OptionStrategy
    account: AccountProfile
    stock: StockOptionContext
    contract: OptionContract

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "account": self.account.to_dict(),
            "stock": self.stock.to_dict(),
            "contract": self.contract.to_dict(),
        }


@dataclass(slots=True)
class OptionEvaluation:
    strategy: OptionStrategy
    symbol: str
    decision: OptionDecision
    capital_required: float
    premium_income: float
    max_loss_estimate: float
    breakeven: float | None
    return_on_capital_pct: float | None
    annualized_return_pct: float | None
    dte: int
    spread_pct: float | None
    violations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    confirmations: list[str] = field(default_factory=list)
    ai_context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "symbol": self.symbol,
            "decision": self.decision,
            "capital_required": round(self.capital_required, 2),
            "premium_income": round(self.premium_income, 2),
            "max_loss_estimate": round(self.max_loss_estimate, 2),
            "breakeven": _round_optional(self.breakeven),
            "return_on_capital_pct": _round_optional(self.return_on_capital_pct),
            "annualized_return_pct": _round_optional(self.annualized_return_pct),
            "dte": self.dte,
            "spread_pct": _round_optional(self.spread_pct),
            "violations": self.violations,
            "warnings": self.warnings,
            "confirmations": self.confirmations,
            "ai_context": self.ai_context,
        }


def _round_optional(value: float | None) -> float | None:
    return None if value is None else round(value, 2)


@dataclass(slots=True)
class SellPutScanConfig:
    min_dte: int = 14
    max_dte: int = 45
    min_otm_pct: float = 0.05
    max_otm_pct: float = 0.30
    max_cash_per_trade_pct: float = 0.4
    max_candidates_per_symbol: int = 12
    include_non_standard: bool = False
    leveraged_symbols: set[str] = field(default_factory=lambda: {"TQQQ", "SQQQ", "SOXL", "SOXS", "NVDL", "TSLL"})


@dataclass(slots=True)
class OptionVolumeSnapshot:
    call_volume: int | None = None
    put_volume: int | None = None

    @property
    def put_call_ratio(self) -> float | None:
        if self.call_volume in (None, 0) or self.put_volume is None:
            return None
        return self.put_volume / self.call_volume

    def to_dict(self) -> dict[str, Any]:
        return {
            "call_volume": self.call_volume,
            "put_volume": self.put_volume,
            "put_call_ratio": _round_optional(self.put_call_ratio),
        }


@dataclass(slots=True)
class SellPutCandidate:
    symbol: str
    underlying_price: float
    expiration: date
    dte: int
    strike: float
    put_symbol: str
    cash_required: float
    cash_required_pct: float
    otm_pct: float
    status: OptionCandidateStatus
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    quote_required: bool = True
    quote_access: str = "missing"
    option_volume: OptionVolumeSnapshot | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "underlying_price": round(self.underlying_price, 2),
            "expiration": self.expiration.isoformat(),
            "dte": self.dte,
            "strike": round(self.strike, 2),
            "put_symbol": self.put_symbol,
            "cash_required": round(self.cash_required, 2),
            "cash_required_pct": round(self.cash_required_pct, 2),
            "otm_pct": round(self.otm_pct, 2),
            "status": self.status,
            "reasons": self.reasons,
            "warnings": self.warnings,
            "quote_required": self.quote_required,
            "quote_access": self.quote_access,
            "option_volume": self.option_volume.to_dict() if self.option_volume else None,
        }


@dataclass(slots=True)
class SellPutScanResult:
    symbol: str
    generated_at_beijing: str
    candidates: list[SellPutCandidate]
    rejected_count: int
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "generated_at_beijing": self.generated_at_beijing,
            "candidate_count": len(self.candidates),
            "rejected_count": self.rejected_count,
            "notes": self.notes,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
        }
