"""Generate account health and risk reports from read-only Longbridge data."""

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


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate read-only account health and risk reports.")
    parser.add_argument("--as-of", default=date.today().isoformat(), help="Analysis date, YYYY-MM-DD")
    parser.add_argument("--currency", default="USD")
    parser.add_argument("--day-trades-5d", type=int, help="Optional manual PDT day-trade count for the last 5 business days.")
    parser.add_argument("--json", action="store_true", help="Print full run result as JSON.")
    args = parser.parse_args()

    from quant_platform.services.portfolio_health import AccountHealthService

    settings = load_settings(PROJECT_ROOT / "config" / "settings.example.yaml")
    result = AccountHealthService(settings).generate(
        as_of=date.fromisoformat(args.as_of),
        currency=args.currency,
        day_trade_count_5d=args.day_trades_5d,
    )
    payload = {
        "generated_at_beijing": result.generated_at_beijing,
        "position_count": result.position_count,
        "health_score": result.health_score,
        "health_state": result.health_state,
        "warning_count": result.warning_count,
        "json_path": str(result.json_path),
        "markdown_path": str(result.markdown_path),
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(
            "SUCCESS account-health "
            f"positions={result.position_count} "
            f"score={result.health_score} "
            f"state={result.health_state} "
            f"warnings={result.warning_count} "
            f"json={result.json_path} "
            f"markdown={result.markdown_path}"
        )


if __name__ == "__main__":
    main()
