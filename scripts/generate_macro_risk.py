"""Generate macro, sentiment, and news risk snapshot."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from quant_platform.config import default_settings_path, load_settings
from quant_platform.console_output import quiet_known_native_stderr
from quant_platform.services.macro_risk import MacroRiskService
from quant_platform.time_utils import latest_completed_us_market_date, now_beijing


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a read-only macro/news/sentiment risk snapshot.")
    parser.add_argument("--symbol", action="append", default=[], help="Symbol to include in Longbridge news checks. Repeatable.")
    parser.add_argument("--news-limit-per-symbol", type=int, default=3)
    parser.add_argument("--json", action="store_true", help="Print full JSON result instead of a concise success line.")
    args = parser.parse_args()

    settings = load_settings(default_settings_path(PROJECT_ROOT))
    with quiet_known_native_stderr():
        result = MacroRiskService(settings).generate(
            market_date_us=latest_completed_us_market_date(now_beijing()),
            symbols=args.symbol,
            news_limit_per_symbol=args.news_limit_per_symbol,
        )

    payload = {
        "generated_at_beijing": result.generated_at_beijing,
        "market_date_us": result.market_date_us,
        "risk_state": result.risk_state,
        "sentiment_state": result.sentiment_state,
        "news_item_count": result.news_item_count,
        "warnings": result.warnings,
        "json_path": str(result.json_path),
        "markdown_path": str(result.markdown_path),
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(
            "SUCCESS macro-risk "
            f"market_date_us={result.market_date_us} "
            f"risk_state={result.risk_state} "
            f"sentiment={result.sentiment_state} "
            f"news={result.news_item_count} "
            f"json={result.json_path} "
            f"markdown={result.markdown_path}"
        )


if __name__ == "__main__":
    main()
