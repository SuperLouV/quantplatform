"""Scan SELL PUT candidates using Longbridge option chain data without quote access."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from quant_platform.clients import LongbridgeCLIClient
from quant_platform.config import load_settings
from quant_platform.options import AccountProfile, OptionsAssistantService, SellPutScanConfig


def main() -> None:
    parser = argparse.ArgumentParser(description="Scan conservative SELL PUT candidates without option quote access.")
    parser.add_argument("symbol")
    parser.add_argument("--config", default="config/settings.example.yaml")
    parser.add_argument("--as-of", default=date.today().isoformat())
    parser.add_argument("--equity", type=float, default=5_000)
    parser.add_argument("--cash", type=float, default=5_000)
    parser.add_argument("--min-dte", type=int, default=14)
    parser.add_argument("--max-dte", type=int, default=45)
    parser.add_argument("--min-otm-pct", type=float, default=5.0)
    parser.add_argument("--max-otm-pct", type=float, default=30.0)
    parser.add_argument("--max-cash-pct", type=float, default=40.0)
    parser.add_argument("--limit", type=int, default=12)
    args = parser.parse_args()

    settings = load_settings(PROJECT_ROOT / args.config)
    client = LongbridgeCLIClient.from_data_config(settings.data)
    symbol = args.symbol.upper()
    as_of = date.fromisoformat(args.as_of)
    quote = client.fetch_quote_snapshot(symbol)
    underlying_price = _required_float(quote.get("current_price") or quote.get("regular_market_price"), "underlying price")
    expirations = [
        expiration
        for expiration in client.fetch_option_expirations(symbol)
        if args.min_dte <= (expiration - as_of).days <= args.max_dte
    ]
    chains = {expiration: client.fetch_option_chain(symbol, expiration) for expiration in expirations}
    volume = _safe_option_volume(client, symbol)
    result = OptionsAssistantService().scan_sell_put(
        symbol=symbol,
        underlying_price=underlying_price,
        as_of=as_of,
        account=AccountProfile(equity=args.equity, cash=args.cash, max_cash_per_trade_pct=args.max_cash_pct / 100),
        expirations=expirations,
        chains_by_expiration=chains,
        option_volume_payload=volume,
        config=SellPutScanConfig(
            min_dte=args.min_dte,
            max_dte=args.max_dte,
            min_otm_pct=args.min_otm_pct / 100,
            max_otm_pct=args.max_otm_pct / 100,
            max_cash_per_trade_pct=args.max_cash_pct / 100,
            max_candidates_per_symbol=args.limit,
        ),
    )
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))


def _safe_option_volume(client: LongbridgeCLIClient, symbol: str) -> dict[str, object] | None:
    try:
        return client.fetch_option_volume(symbol)
    except Exception:  # noqa: BLE001 - volume is an optional context signal.
        return None


def _required_float(value: object, label: str) -> float:
    if value in (None, ""):
        raise ValueError(f"Missing {label}")
    return float(value)


if __name__ == "__main__":
    main()
