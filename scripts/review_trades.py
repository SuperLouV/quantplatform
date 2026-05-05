"""Generate historical trade review reports from read-only Longbridge records."""

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

from quant_platform.config import default_settings_path, load_settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a read-only historical trade review report.")
    parser.add_argument("--start", help="Start date, YYYY-MM-DD")
    parser.add_argument("--end", help="End date, YYYY-MM-DD")
    parser.add_argument("--json", action="store_true", help="Print run result as JSON.")
    args = parser.parse_args()

    from quant_platform.services.trade_review import TradeReviewService

    settings = load_settings(default_settings_path(PROJECT_ROOT))
    result = TradeReviewService(settings).generate(
        start=date.fromisoformat(args.start) if args.start else None,
        end=date.fromisoformat(args.end) if args.end else None,
    )
    payload = {
        "generated_at_beijing": result.generated_at_beijing,
        "execution_count": result.execution_count,
        "closed_trade_count": result.closed_trade_count,
        "error_count": result.error_count,
        "json_path": str(result.json_path),
        "markdown_path": str(result.markdown_path),
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(
            "SUCCESS trade-review "
            f"executions={result.execution_count} "
            f"closed_trades={result.closed_trade_count} "
            f"errors={result.error_count} "
            f"json={result.json_path} "
            f"markdown={result.markdown_path}"
        )


if __name__ == "__main__":
    main()
