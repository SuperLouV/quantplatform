"""Longbridge Terminal CLI read-only data client."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from datetime import date
from typing import Any

from quant_platform.config import DataConfig
from quant_platform.time_utils import iso_beijing


class LongbridgeCLIError(RuntimeError):
    """Raised when the local Longbridge CLI is unavailable or returns invalid data."""


@dataclass(slots=True)
class LongbridgeCLIClient:
    provider_name = "longbridge_cli"

    binary: str = "longbridge"
    timeout_seconds: float = 15.0

    @classmethod
    def from_data_config(cls, config: DataConfig) -> "LongbridgeCLIClient":
        return cls(
            binary=config.longbridge_cli_binary,
            timeout_seconds=config.request_timeout_seconds,
        )

    def fetch_quote_snapshot(self, symbol: str) -> dict[str, Any]:
        raw = self.fetch_quote(symbol)
        return normalize_quote_snapshot(raw, requested_symbol=symbol)

    def fetch_quote(self, symbol: str) -> dict[str, Any]:
        provider_symbol = to_longbridge_symbol(symbol)
        command = [self.binary, "quote", provider_symbol, "--format", "json"]
        try:
            result = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
        except FileNotFoundError as exc:
            raise LongbridgeCLIError(
                f"Longbridge CLI not found: {self.binary}. Install longbridge-terminal and run auth login."
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise LongbridgeCLIError(f"Longbridge CLI quote timed out for {provider_symbol}.") from exc

        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            raise LongbridgeCLIError(f"Longbridge CLI quote failed for {provider_symbol}: {detail}")

        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise LongbridgeCLIError("Longbridge CLI returned non-JSON quote output.") from exc

        if not isinstance(payload, list) or not payload or not isinstance(payload[0], dict):
            raise LongbridgeCLIError("Longbridge CLI quote output must be a non-empty JSON array.")
        return payload[0]


def to_longbridge_symbol(symbol: str) -> str:
    normalized = symbol.strip().upper()
    if not normalized:
        raise LongbridgeCLIError("symbol is required")
    if "." in normalized:
        return normalized
    return f"{normalized}.US"


def normalize_quote_snapshot(raw: dict[str, Any], *, requested_symbol: str) -> dict[str, Any]:
    symbol = _internal_symbol(str(raw.get("symbol") or requested_symbol))
    regular_last = _optional_float(raw.get("last"))
    previous_close = _optional_float(raw.get("prev_close"))
    pre_market = _quote_block(raw.get("pre_market_quote"))
    post_market = _quote_block(raw.get("post_market_quote"))
    overnight = _quote_block(raw.get("overnight_quote"))
    current_price = (
        (overnight or {}).get("last")
        or (post_market or {}).get("last")
        or (pre_market or {}).get("last")
        or regular_last
    )
    change_percent = None
    if current_price is not None and previous_close not in (None, 0):
        change_percent = ((current_price - previous_close) / previous_close) * 100

    return {
        "symbol": symbol,
        "provider": LongbridgeCLIClient.provider_name,
        "quote_provider": LongbridgeCLIClient.provider_name,
        "quote_provider_status": "success",
        "company_name": None,
        "sector": None,
        "industry": None,
        "exchange": "US",
        "currency": "USD",
        "open_price": _optional_float(raw.get("open")),
        "high_price": _optional_float(raw.get("high")),
        "low_price": _optional_float(raw.get("low")),
        "latest_close": regular_last,
        "current_price": current_price,
        "regular_market_price": regular_last,
        "pre_market_price": (pre_market or {}).get("last"),
        "post_market_price": (post_market or {}).get("last"),
        "overnight_price": (overnight or {}).get("last"),
        "market_state": _market_state(pre_market=pre_market, post_market=post_market, overnight=overnight),
        "latest_history_date_us": _latest_quote_date(pre_market=pre_market, post_market=post_market, overnight=overnight),
        "snapshot_refreshed_at_beijing": iso_beijing(),
        "market_timezone": "America/New_York",
        "previous_close": previous_close,
        "change_percent": change_percent,
        "latest_volume": _optional_float(raw.get("volume")),
        "latest_turnover": _optional_float(raw.get("turnover")),
        "market_cap": None,
        "avg_dollar_volume": None,
        "trailing_pe": None,
        "forward_pe": None,
        "next_earnings_date": None,
        "longbridge_symbol": raw.get("symbol"),
        "longbridge_status": raw.get("status"),
        "longbridge_pre_market_quote": pre_market,
        "longbridge_post_market_quote": post_market,
        "longbridge_overnight_quote": overnight,
    }


def _quote_block(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return {
        "high": _optional_float(value.get("high")),
        "last": _optional_float(value.get("last")),
        "low": _optional_float(value.get("low")),
        "prev_close": _optional_float(value.get("prev_close")),
        "timestamp": value.get("timestamp"),
        "turnover": _optional_float(value.get("turnover")),
        "volume": _optional_float(value.get("volume")),
    }


def _market_state(
    *,
    pre_market: dict[str, Any] | None,
    post_market: dict[str, Any] | None,
    overnight: dict[str, Any] | None,
) -> str:
    if overnight and overnight.get("last") is not None:
        return "OVERNIGHT"
    if post_market and post_market.get("last") is not None:
        return "POST"
    if pre_market and pre_market.get("last") is not None:
        return "PRE"
    return "REGULAR"


def _latest_quote_date(
    *,
    pre_market: dict[str, Any] | None,
    post_market: dict[str, Any] | None,
    overnight: dict[str, Any] | None,
) -> str | None:
    for quote in (overnight, post_market, pre_market):
        timestamp = quote.get("timestamp") if quote else None
        if not timestamp:
            continue
        parsed = _date_from_timestamp(str(timestamp))
        if parsed:
            return parsed.isoformat()
    return None


def _date_from_timestamp(value: str) -> date | None:
    try:
        return date.fromisoformat(value.split(" ", 1)[0])
    except ValueError:
        return None


def _internal_symbol(symbol: str) -> str:
    return symbol.split(".", 1)[0].upper()


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(value)
