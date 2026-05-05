"""Generate account-aware covered call and cash-secured put advice."""

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
    parser = argparse.ArgumentParser(description="Generate read-only options advice for real Longbridge holdings.")
    parser.add_argument("--as-of", default=date.today().isoformat(), help="Analysis date, YYYY-MM-DD")
    parser.add_argument("--min-dte", type=int, default=14)
    parser.add_argument("--max-dte", type=int, default=45)
    parser.add_argument("--max-positions", type=int)
    parser.add_argument("--max-workers", type=int, default=2)
    parser.add_argument("--timeout-seconds", type=float, default=60)
    parser.add_argument("--max-expirations-per-symbol", type=int, default=2)
    parser.add_argument("--json", action="store_true", help="Print full JSON result instead of a concise success line.")
    args = parser.parse_args()

    with quiet_known_native_stderr():
        from quant_platform.options.advice import AccountOptionsAdviceService

        settings = load_settings(PROJECT_ROOT / "config" / "settings.example.yaml")
        result = AccountOptionsAdviceService(settings).generate(
            as_of=date.fromisoformat(args.as_of),
            min_dte=args.min_dte,
            max_dte=args.max_dte,
            max_positions=args.max_positions,
            max_workers=args.max_workers,
            timeout_seconds=args.timeout_seconds,
            max_expirations_per_symbol=args.max_expirations_per_symbol,
        )

    payload = {
        "generated_at_beijing": result.generated_at_beijing,
        "position_count": result.position_count,
        "advice_count": result.advice_count,
        "error_count": result.error_count,
        "json_path": str(result.json_path),
        "markdown_path": str(result.markdown_path),
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(
            "SUCCESS options-advice "
            f"positions={result.position_count} "
            f"advice={result.advice_count} "
            f"errors={result.error_count} "
            f"json={result.json_path} "
            f"markdown={result.markdown_path}"
        )


if __name__ == "__main__":
    main()
