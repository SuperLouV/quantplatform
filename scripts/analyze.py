"""Generate automated structured AI analysis from local snapshots."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from quant_platform.config import load_settings
from quant_platform.console_output import quiet_known_native_stderr


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate JSON and Markdown AI analysis reports from local structured data.")
    parser.add_argument("--pool-id", default="longbridge_core", help="Pool id to include; use all for all local snapshots.")
    parser.add_argument("--max-symbols", type=int, default=40)
    parser.add_argument("--no-model", action="store_true", help="Skip OpenAI-compatible model calls and only write rule-layer output.")
    parser.add_argument("--json", action="store_true", help="Print full JSON result instead of a concise success line.")
    args = parser.parse_args()

    with quiet_known_native_stderr():
        from quant_platform.services.ai_analysis import AutomatedAIAnalysisService

        settings = load_settings(PROJECT_ROOT / "config" / "settings.example.yaml")
        result = AutomatedAIAnalysisService(settings).analyze_dashboard(
            pool_id=args.pool_id,
            max_symbols=args.max_symbols,
            use_model=not args.no_model,
        )

    payload = {
        "generated_at_beijing": result.generated_at_beijing,
        "snapshot_count": result.snapshot_count,
        "model_status": result.model_status,
        "warnings": result.warnings,
        "json_path": str(result.json_path),
        "markdown_path": str(result.markdown_path),
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(
            "SUCCESS analyze "
            f"snapshots={result.snapshot_count} "
            f"model_status={result.model_status} "
            f"json={result.json_path} "
            f"markdown={result.markdown_path}"
        )


if __name__ == "__main__":
    main()
