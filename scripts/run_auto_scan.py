"""Run the stock and options scanner once or on a simple interval."""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from quant_platform.config import default_settings_path, load_settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Run read-only automated stock/options scans.")
    parser.add_argument("--pool-id", default="longbridge_core")
    parser.add_argument("--as-of", default=date.today().isoformat())
    parser.add_argument("--min-dte", type=int, default=14)
    parser.add_argument("--max-dte", type=int, default=45)
    parser.add_argument("--max-positions", type=int)
    parser.add_argument("--csp-watch-limit", type=int, default=10)
    parser.add_argument("--repeat", action="store_true", help="Keep running at --interval-minutes until interrupted.")
    parser.add_argument("--interval-minutes", type=float, default=60)
    parser.add_argument("--json", action="store_true", help="Print JSON run result.")
    args = parser.parse_args()

    from quant_platform.services.auto_scanner import AutoScannerService

    settings = load_settings(default_settings_path(PROJECT_ROOT))
    service = AutoScannerService(settings)
    while True:
        result = service.run(
            pool_id=args.pool_id,
            as_of=date.fromisoformat(args.as_of),
            min_dte=args.min_dte,
            max_dte=args.max_dte,
            max_positions=args.max_positions,
            csp_watch_limit=args.csp_watch_limit,
        )
        payload = {
            "generated_at_beijing": result.generated_at_beijing,
            "pool_id": result.pool_id,
            "stock_candidate_count": result.stock_candidate_count,
            "covered_call_count": result.covered_call_count,
            "cash_secured_put_count": result.cash_secured_put_count,
            "error_count": result.error_count,
            "json_path": str(result.json_path),
            "markdown_path": str(result.markdown_path),
        }
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(
                "SUCCESS auto-scan "
                f"pool={result.pool_id} "
                f"stocks={result.stock_candidate_count} "
                f"covered_call={result.covered_call_count} "
                f"cash_secured_put={result.cash_secured_put_count} "
                f"errors={result.error_count} "
                f"json={result.json_path} "
                f"markdown={result.markdown_path}"
            )
        if not args.repeat:
            return
        time.sleep(max(args.interval_minutes, 1) * 60)


if __name__ == "__main__":
    main()
