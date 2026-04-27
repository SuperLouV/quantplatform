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
from quant_platform.services.daily_report import DailyReportService


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a local QuantPlatform daily Markdown report.")
    parser.add_argument("--pool-id", default="default_core", help="Stock pool id used by the scanner.")
    parser.add_argument("--market-date-us", help="US market date for the report, YYYY-MM-DD. Defaults to latest refresh summary.")
    args = parser.parse_args()

    settings = load_settings(PROJECT_ROOT / "config" / "settings.example.yaml")
    service = DailyReportService(settings)
    result = service.generate(
        pool_id=args.pool_id,
        market_date_us=date.fromisoformat(args.market_date_us) if args.market_date_us else None,
    )
    print(
        json.dumps(
            {
                "pool_id": result.pool_id,
                "market_date_us": result.market_date_us.isoformat(),
                "generated_at_beijing": result.generated_at_beijing,
                "path": str(result.path),
                "scanner_count": result.scanner_count,
                "market_events_count": result.market_events_count,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
