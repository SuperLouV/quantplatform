"""Structured models for conservative options strategy analysis."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any, Literal


OptionType = Literal["put", "call"]
OptionStrategy = Literal["cash_secured_put", "covered_call"]
OptionDecision = Literal["符合策略", "继续观察", "不适合"]


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
