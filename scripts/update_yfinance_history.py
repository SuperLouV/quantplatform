"""Fetch and store historical OHLCV data from yfinance."""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from quant_platform.config import load_settings
from quant_platform.console_output import quiet_known_native_stderr


def main() -> None:
    parser = argparse.ArgumentParser(description="Update yfinance history for one US symbol.")
    parser.add_argument("symbol", help="Ticker symbol, for example AAPL")
    parser.add_argument("--start", help="Optional start date in YYYY-MM-DD format")
    parser.add_argument("--end", help="Optional end date in YYYY-MM-DD format")
    parser.add_argument("--interval", default="1d", help="Bar interval, default 1d")
    parser.add_argument("--years", type=int, help="Override initial daily history backfill years, for example 10")
    parser.add_argument(
        "--full-history",
        action="store_true",
        help="Fetch from a very early start date so yfinance returns the longest available history.",
    )
    parser.add_argument(
        "--no-adjust",
        action="store_true",
        help="Disable adjusted prices and use raw close values",
    )
    args = parser.parse_args()
    if args.start and args.full_history:
        parser.error("--start and --full-history cannot be used together")
    if args.years is not None and args.years <= 0:
        parser.error("--years must be a positive integer")

    project_root = Path(__file__).resolve().parents[1]
    settings = load_settings(project_root / "config" / "settings.example.yaml")
    if args.years is not None:
        settings.data.yfinance_initial_history_years = args.years

    with quiet_known_native_stderr():
        from quant_platform.services import YFinanceHistoryUpdater

        updater = YFinanceHistoryUpdater(settings)
        result = updater.update_symbol(
            args.symbol.upper(),
            start=_parse_date(args.start),
            end=_parse_date(args.end),
            interval=args.interval,
            adjusted=not args.no_adjust,
            full_history=args.full_history,
        )

    print(
        "SUCCESS history-refresh "
        f"symbol={result.symbol} "
        f"start_reason={result.start_reason} "
        f"requested_start={result.requested_start or '-'} "
        f"rows_fetched={result.rows_written} "
        f"total_rows={result.total_rows} "
        f"earliest={result.earliest_date or '-'} "
        f"latest={result.latest_date or '-'} "
        f"cursor={result.cursor or '-'}"
    )


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value)


if __name__ == "__main__":
    main()
