"""Update local history for market overview proxies."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from quant_platform.config import load_settings
from quant_platform.services.market_overview import MARKET_OVERVIEW_SYMBOLS
from quant_platform.services.yfinance_history import YFinanceHistoryUpdater
from quant_platform.time_utils import latest_completed_us_market_date, now_beijing


def main() -> None:
    parser = argparse.ArgumentParser(description="Update local yfinance history for market overview symbols.")
    parser.add_argument("--market-date-us", help="US market date to refresh, YYYY-MM-DD. Defaults to latest completed US session.")
    parser.add_argument("--symbols", nargs="*", help="Override the default market overview symbol list.")
    args = parser.parse_args()

    market_date = date.fromisoformat(args.market_date_us) if args.market_date_us else latest_completed_us_market_date(now_beijing())
    symbols = args.symbols or list(MARKET_OVERVIEW_SYMBOLS)
    settings = load_settings(PROJECT_ROOT / "config" / "settings.example.yaml")
    updater = YFinanceHistoryUpdater(settings)

    results: dict[str, dict[str, object]] = {}
    for symbol in symbols:
        try:
            result = updater.update_symbol(symbol, end=market_date + timedelta(days=1))
            results[symbol] = {
                "status": "success" if result.cursor and result.cursor >= market_date.isoformat() else "empty",
                "rows_written": result.rows_written,
                "cursor": result.cursor,
                "processed_path": str(result.processed_path),
            }
        except Exception as exc:  # noqa: BLE001 - keep refreshing other market proxies.
            results[symbol] = {"status": "error", "error": str(exc)}

    print(
        json.dumps(
            {
                "market_date_us": market_date.isoformat(),
                "symbols": len(symbols),
                "success": sum(1 for item in results.values() if item.get("status") == "success"),
                "empty": sum(1 for item in results.values() if item.get("status") == "empty"),
                "error": sum(1 for item in results.values() if item.get("status") == "error"),
                "results": results,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
