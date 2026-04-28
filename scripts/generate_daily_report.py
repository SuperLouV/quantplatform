"""Generate a Chinese daily report from local refreshed market data."""

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
    parser = argparse.ArgumentParser(description="Generate a local QuantPlatform daily Markdown report.")
    parser.add_argument("--pool-id", default="default_core", help="Stock pool id used by the scanner.")
    parser.add_argument("--market-date-us", help="US market date for the report, YYYY-MM-DD. Defaults to latest refresh summary.")
    parser.add_argument("--json", action="store_true", help="Print full JSON result instead of a concise success line.")
    args = parser.parse_args()

    with quiet_known_native_stderr():
        from quant_platform.services.daily_report import DailyReportService

        settings = load_settings(PROJECT_ROOT / "config" / "settings.example.yaml")
        service = DailyReportService(settings)
        result = service.generate(
            pool_id=args.pool_id,
            market_date_us=date.fromisoformat(args.market_date_us) if args.market_date_us else None,
        )
    payload = {
        "pool_id": result.pool_id,
        "market_date_us": result.market_date_us.isoformat(),
        "generated_at_beijing": result.generated_at_beijing,
        "path": str(result.path),
        "scanner_count": result.scanner_count,
        "market_events_count": result.market_events_count,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(
            "SUCCESS daily-report "
            f"pool={payload['pool_id']} "
            f"market_date_us={payload['market_date_us']} "
            f"scanner_count={payload['scanner_count']} "
            f"market_events={payload['market_events_count']} "
            f"path={payload['path']}"
        )


if __name__ == "__main__":
    main()
