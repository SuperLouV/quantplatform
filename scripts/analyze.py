"""Generate model-backed AI analysis from local structured reports."""

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
    parser.add_argument(
        "--mode",
        choices=["dashboard", "account", "options", "stock"],
        default="dashboard",
        help="Analysis mode. dashboard keeps the legacy snapshot summary; account/options/stock call the model-backed interpreter.",
    )
    parser.add_argument("--symbol", help="Symbol for --mode stock.")
    parser.add_argument("--pool-id", default="longbridge_core", help="Pool id to include; use all for all local snapshots.")
    parser.add_argument("--max-symbols", type=int, default=40)
    parser.add_argument("--no-model", action="store_true", help="Skip OpenAI-compatible model calls and only write input-summary output.")
    parser.add_argument("--json", action="store_true", help="Print full JSON result instead of a concise success line.")
    args = parser.parse_args()

    with quiet_known_native_stderr():
        from quant_platform.services.ai_analysis import AutomatedAIAnalysisService

        settings = load_settings(PROJECT_ROOT / "config" / "settings.example.yaml")
        service = AutomatedAIAnalysisService(settings)
        if args.mode == "dashboard":
            result = service.analyze_dashboard(
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
            success_line = (
                "SUCCESS analyze "
                f"snapshots={result.snapshot_count} "
                f"model_status={result.model_status} "
                f"json={result.json_path} "
                f"markdown={result.markdown_path}"
            )
        elif args.mode == "account":
            result = service.analyze_latest_account_health(use_model=not args.no_model)
            payload, success_line = _interpretation_output(result, "ai-analyze")
        elif args.mode == "options":
            result = service.analyze_latest_options_advice(use_model=not args.no_model)
            payload, success_line = _interpretation_output(result, "ai-options")
        else:
            if not args.symbol:
                parser.error("--symbol is required for --mode stock")
            result = service.analyze_stock_technical(args.symbol, use_model=not args.no_model)
            payload, success_line = _interpretation_output(result, "ai-stock")

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(success_line)


def _interpretation_output(result: object, command_name: str) -> tuple[dict[str, object], str]:
    payload = {
        "generated_at_beijing": getattr(result, "generated_at_beijing"),
        "scenario": getattr(result, "scenario"),
        "target_id": getattr(result, "target_id"),
        "model_status": getattr(result, "model_status"),
        "warnings": getattr(result, "warnings"),
        "source_paths": [str(path) for path in getattr(result, "source_paths")],
        "json_path": str(getattr(result, "json_path")),
        "markdown_path": str(getattr(result, "markdown_path")),
    }
    success_line = (
        f"SUCCESS {command_name} "
        f"scenario={payload['scenario']} "
        f"target={payload['target_id']} "
        f"model_status={payload['model_status']} "
        f"json={payload['json_path']} "
        f"markdown={payload['markdown_path']}"
    )
    return payload, success_line


if __name__ == "__main__":
    main()
