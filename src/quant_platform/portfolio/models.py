"""Read-only account and position models."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from quant_platform.options import AccountProfile


@dataclass(slots=True)
class CashBalance:
    currency: str
    total_cash: float | None = None
    available_cash: float | None = None
    frozen_cash: float | None = None
    settling_cash: float | None = None
    withdraw_cash: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class AccountPosition:
    symbol: str
    name: str | None = None
    currency: str | None = None
    market: str | None = None
    quantity: float = 0
    available_quantity: float = 0
    cost_price: float | None = None
    market_price: float | None = None
    market_value: float | None = None
    previous_close: float | None = None

    @property
    def internal_symbol(self) -> str:
        return self.symbol.split(".", 1)[0].upper()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["internal_symbol"] = self.internal_symbol
        return payload


@dataclass(slots=True)
class AccountSnapshot:
    provider: str
    generated_at_beijing: str
    currency: str = "USD"
    net_assets: float | None = None
    total_asset: float | None = None
    market_value: float | None = None
    total_cash: float | None = None
    available_cash: float | None = None
    buy_power: float | None = None
    total_pl: float | None = None
    total_today_pl: float | None = None
    margin_call: float | None = None
    risk_level: str | None = None
    cash_balances: list[CashBalance] = field(default_factory=list)
    positions: list[AccountPosition] = field(default_factory=list)

    @property
    def equity_for_risk(self) -> float:
        return float(self.net_assets or self.total_asset or 0)

    @property
    def cash_for_cash_secured_put(self) -> float:
        # Conservative by design: do not treat margin buying power as cash for CSP.
        return float(self.available_cash or self.total_cash or 0)

    def position_for(self, symbol: str) -> AccountPosition | None:
        normalized = symbol.split(".", 1)[0].upper()
        for position in self.positions:
            if position.internal_symbol == normalized:
                return position
        return None

    def to_options_account(self, symbol: str | None = None, *, max_cash_per_trade_pct: float = 0.4) -> AccountProfile:
        position = self.position_for(symbol) if symbol else None
        return AccountProfile(
            equity=self.equity_for_risk,
            cash=self.cash_for_cash_secured_put,
            max_cash_per_trade_pct=max_cash_per_trade_pct,
            stock_shares=int(position.available_quantity) if position else 0,
            stock_cost_basis=position.cost_price if position else None,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "generated_at_beijing": self.generated_at_beijing,
            "currency": self.currency,
            "net_assets": _round_optional(self.net_assets),
            "total_asset": _round_optional(self.total_asset),
            "market_value": _round_optional(self.market_value),
            "total_cash": _round_optional(self.total_cash),
            "available_cash": _round_optional(self.available_cash),
            "buy_power": _round_optional(self.buy_power),
            "total_pl": _round_optional(self.total_pl),
            "total_today_pl": _round_optional(self.total_today_pl),
            "margin_call": _round_optional(self.margin_call),
            "risk_level": self.risk_level,
            "cash_for_cash_secured_put": round(self.cash_for_cash_secured_put, 2),
            "position_count": len(self.positions),
            "cash_balances": [cash.to_dict() for cash in self.cash_balances],
            "positions": [position.to_dict() for position in self.positions],
        }


def _round_optional(value: float | None) -> float | None:
    return None if value is None else round(float(value), 2)
