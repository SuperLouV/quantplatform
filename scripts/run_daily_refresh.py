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
from quant_platform.console_output import quiet_known_native_stderr


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
    parser.add_argument("--json", action="store_true", help="Print full JSON result instead of a concise success line.")
    args = parser.parse_args()

    pool_path = Path(args.pool)
    if not pool_path.is_absolute():
        pool_path = PROJECT_ROOT / pool_path

    with quiet_known_native_stderr():
        from quant_platform.services.daily_refresh import DailyRefreshService

        settings = load_settings(PROJECT_ROOT / "config" / "settings.example.yaml")
        service = DailyRefreshService(settings)
        result = service.run(
            pool_path=pool_path,
            market_date_us=date.fromisoformat(args.market_date_us) if args.market_date_us else None,
            workers=args.workers,
            update_events=not args.skip_events,
        )
    payload = {
        "pool_id": result.pool_id,
        "market_date_us": result.market_date_us.isoformat(),
        "generated_at_beijing": result.generated_at_beijing,
        "snapshot_count": result.snapshot_count,
        "dashboard_path": str(result.dashboard_path),
        "summary_path": str(result.summary_path),
        "market_events_count": result.market_events_count,
        "history_success": _count_history(result.history, "success"),
        "history_empty": _count_history(result.history, "empty"),
        "history_error": _count_history(result.history, "error"),
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(
            "SUCCESS daily-refresh "
            f"pool={payload['pool_id']} "
            f"market_date_us={payload['market_date_us']} "
            f"snapshots={payload['snapshot_count']} "
            f"history_success={payload['history_success']} "
            f"history_empty={payload['history_empty']} "
            f"history_error={payload['history_error']} "
            f"market_events={payload['market_events_count']} "
            f"summary={payload['summary_path']}"
        )


def _count_history(history: dict[str, dict[str, object]], status: str) -> int:
    return sum(1 for item in history.values() if item.get("status") == status)


if __name__ == "__main__":
    main()
