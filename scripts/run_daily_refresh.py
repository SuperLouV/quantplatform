"""Run the end-of-day refresh pipeline for a stock pool."""

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

from quant_platform.config import load_settings
from quant_platform.services.daily_refresh import DailyRefreshService


def main() -> None:
    parser = argparse.ArgumentParser(description="Run daily market close refresh for a stock pool.")
    parser.add_argument(
        "--pool",
        default="data/reference/system/stock_pools/preset/default_core.json",
        help="Pool JSON path, relative to project root unless absolute.",
    )
    parser.add_argument("--market-date-us", help="US market date to refresh, YYYY-MM-DD. Defaults to latest US weekday.")
    parser.add_argument("--workers", type=int, default=8, help="Parallel workers for quote snapshots.")
    parser.add_argument("--skip-events", action="store_true", help="Skip market event refresh.")
    args = parser.parse_args()

    pool_path = Path(args.pool)
    if not pool_path.is_absolute():
        pool_path = PROJECT_ROOT / pool_path

    settings = load_settings(PROJECT_ROOT / "config" / "settings.example.yaml")
    service = DailyRefreshService(settings)
    result = service.run(
        pool_path=pool_path,
        market_date_us=date.fromisoformat(args.market_date_us) if args.market_date_us else None,
        workers=args.workers,
        update_events=not args.skip_events,
    )
    print(
        json.dumps(
            {
                "pool_id": result.pool_id,
                "market_date_us": result.market_date_us.isoformat(),
                "generated_at_beijing": result.generated_at_beijing,
                "snapshot_count": result.snapshot_count,
                "dashboard_path": str(result.dashboard_path),
                "summary_path": str(result.summary_path),
                "market_events_count": result.market_events_count,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
