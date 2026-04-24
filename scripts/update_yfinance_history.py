"""Fetch and store historical OHLCV data from yfinance."""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from quant_platform.config import load_settings
from quant_platform.services import YFinanceHistoryUpdater


def main() -> None:
    parser = argparse.ArgumentParser(description="Update yfinance history for one US symbol.")
    parser.add_argument("symbol", help="Ticker symbol, for example AAPL")
    parser.add_argument("--start", help="Optional start date in YYYY-MM-DD format")
    parser.add_argument("--end", help="Optional end date in YYYY-MM-DD format")
    parser.add_argument("--interval", default="1d", help="Bar interval, default 1d")
    parser.add_argument(
        "--no-adjust",
        action="store_true",
        help="Disable adjusted prices and use raw close values",
    )
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parents[1]
    settings = load_settings(project_root / "config" / "settings.example.yaml")
    updater = YFinanceHistoryUpdater(settings)

    result = updater.update_symbol(
        args.symbol.upper(),
        start=_parse_date(args.start),
        end=_parse_date(args.end),
        interval=args.interval,
        adjusted=not args.no_adjust,
    )

    print(f"symbol={result.symbol}")
    print(f"rows_written={result.rows_written}")
    print(f"raw_path={result.raw_path}")
    print(f"processed_path={result.processed_path}")
    print(f"cursor={result.cursor}")


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value)


if __name__ == "__main__":
    main()
