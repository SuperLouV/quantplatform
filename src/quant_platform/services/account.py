"""Read-only account service backed by Longbridge Terminal CLI."""

from __future__ import annotations

from typing import Any

from quant_platform.clients import LongbridgeCLIClient
from quant_platform.config import Settings
from quant_platform.portfolio import AccountPosition, AccountSnapshot, CashBalance
from quant_platform.services.operation_log import OperationLogger, operation_log_root
from quant_platform.time_utils import iso_beijing


class LongbridgeAccountService:
    def __init__(self, settings: Settings, client: LongbridgeCLIClient | None = None) -> None:
        self.settings = settings
        self.client = client or LongbridgeCLIClient.from_data_config(settings.data)
        self.logger = OperationLogger(operation_log_root(settings), "account")

    def snapshot(self, *, currency: str = "USD") -> AccountSnapshot:
        self.logger.info("longbridge_account.fetch.start", provider=self.client.provider_name, currency=currency)
        try:
            assets = self.client.fetch_assets(currency=currency)
            portfolio = self.client.fetch_portfolio()
            positions = self.client.fetch_positions()
            snapshot = normalize_longbridge_account(
                assets_payload=assets,
                portfolio_payload=portfolio,
                positions_payload=positions,
                provider=self.client.provider_name,
            )
            self.logger.info(
                "longbridge_account.fetch.success",
                provider=snapshot.provider,
                currency=snapshot.currency,
                position_count=len(snapshot.positions),
                risk_level=snapshot.risk_level,
            )
            return snapshot
        except Exception as exc:
            self.logger.error(
                "longbridge_account.fetch.error",
                provider=self.client.provider_name,
                currency=currency,
                error=str(exc),
            )
            raise


def normalize_longbridge_account(
    *,
    assets_payload: dict[str, Any] | list[Any],
    portfolio_payload: dict[str, Any],
    positions_payload: list[dict[str, Any]],
    provider: str = "longbridge_cli",
) -> AccountSnapshot:
    assets = _first_object(assets_payload)
    overview = portfolio_payload.get("overview") if isinstance(portfolio_payload.get("overview"), dict) else {}
    cash_balances = _cash_balances(assets, portfolio_payload)
    positions = _positions(portfolio_payload, positions_payload)
    return AccountSnapshot(
        provider=provider,
        generated_at_beijing=iso_beijing(),
        currency=str(overview.get("currency") or assets.get("currency") or "USD"),
        net_assets=_optional_float(assets.get("net_assets")),
        total_asset=_optional_float(overview.get("total_asset")),
        market_value=_optional_float(overview.get("market_cap")),
        total_cash=_optional_float(overview.get("total_cash") or assets.get("total_cash")),
        available_cash=_available_cash(cash_balances),
        buy_power=_optional_float(assets.get("buy_power")),
        total_pl=_optional_float(overview.get("total_pl")),
        total_today_pl=_optional_float(overview.get("total_today_pl")),
        margin_call=_optional_float(overview.get("margin_call") or assets.get("margin_call")),
        risk_level=_risk_level(overview.get("risk_level"), assets.get("risk_level")),
        cash_balances=cash_balances,
        positions=positions,
    )


def _first_object(value: dict[str, Any] | list[Any]) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    for item in value:
        if isinstance(item, dict):
            return item
    return {}


def _cash_balances(assets: dict[str, Any], portfolio: dict[str, Any]) -> list[CashBalance]:
    result: list[CashBalance] = []
    for item in assets.get("cash_infos") or []:
        if not isinstance(item, dict):
            continue
        result.append(
            CashBalance(
                currency=str(item.get("currency") or ""),
                available_cash=_optional_float(item.get("available_cash")),
                frozen_cash=_optional_float(item.get("frozen_cash")),
                settling_cash=_optional_float(item.get("settling_cash")),
                withdraw_cash=_optional_float(item.get("withdraw_cash")),
            )
        )

    seen = {cash.currency for cash in result}
    for item in portfolio.get("cash_balances") or []:
        if not isinstance(item, dict):
            continue
        currency = str(item.get("currency") or "")
        if currency in seen:
            continue
        result.append(
            CashBalance(
                currency=currency,
                total_cash=_optional_float(item.get("total_amount")),
                available_cash=_optional_float(item.get("balance")),
                frozen_cash=_optional_float(item.get("frozen_cash")),
                withdraw_cash=_optional_float(item.get("withdraw_cash")),
            )
        )
    return result


def _positions(portfolio: dict[str, Any], positions_payload: list[dict[str, Any]]) -> list[AccountPosition]:
    portfolio_by_symbol = {
        str(item.get("symbol") or "").upper(): item
        for item in portfolio.get("holdings") or []
        if isinstance(item, dict) and item.get("symbol")
    }
    symbols = list(dict.fromkeys([*(str(item.get("symbol") or "").upper() for item in positions_payload), *portfolio_by_symbol.keys()]))
    result: list[AccountPosition] = []
    for symbol in symbols:
        if not symbol:
            continue
        position = next((item for item in positions_payload if str(item.get("symbol") or "").upper() == symbol), {})
        holding = portfolio_by_symbol.get(symbol, {})
        result.append(
            AccountPosition(
                symbol=symbol,
                name=_optional_str(position.get("name") or holding.get("name")),
                currency=_optional_str(position.get("currency") or holding.get("currency")),
                market=_optional_str(position.get("market")),
                quantity=_optional_float(position.get("quantity") or holding.get("quantity")) or 0,
                available_quantity=_optional_float(
                    position.get("available") or position.get("available_quantity") or holding.get("available_quantity")
                )
                or 0,
                cost_price=_optional_float(position.get("cost_price") or holding.get("cost_price")),
                market_price=_optional_float(holding.get("market_price")),
                market_value=_optional_float(holding.get("market_value_usd") or holding.get("market_value")),
                previous_close=_optional_float(holding.get("prev_close")),
            )
        )
    return result


def _available_cash(cash_balances: list[CashBalance]) -> float | None:
    usd = next((cash for cash in cash_balances if cash.currency.upper() == "USD"), None)
    source = usd or (cash_balances[0] if cash_balances else None)
    return source.available_cash if source else None


def _risk_level(*values: object) -> str | None:
    for value in values:
        if value in (None, ""):
            continue
        if str(value) == "0":
            return "Safe"
        return str(value)
    return None


def _optional_str(value: object) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _optional_float(value: object) -> float | None:
    if value in (None, ""):
        return None
    return float(value)
