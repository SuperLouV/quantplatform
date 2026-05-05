"""Analyze real Longbridge positions and watchlists with local strategy modules."""

from __future__ import annotations

import argparse
from pathlib import Path

from quant_platform.config import load_settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate JSON and Markdown strategy summaries for real Longbridge holdings/watchlists.")
    parser.add_argument(
        "--update-history",
        action="store_true",
        help="Refresh each symbol's yfinance daily history before analysis. Without this, existing local parquet is used.",
    )
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parents[1]
    settings = load_settings(project_root / "config" / "settings.example.yaml")

    from quant_platform.services import PortfolioStrategyService

    result = PortfolioStrategyService(settings).analyze(update_history=args.update_history)
    print(
        "SUCCESS longbridge-portfolio-analysis "
        f"positions={result.position_count} "
        f"watchlist={result.watchlist_count} "
        f"combined={result.combined_count} "
        f"quote_success={result.quote_success_count} "
        f"quote_error={result.quote_error_count} "
        f"history_error={result.history_error_count} "
        f"json={result.json_path} "
        f"markdown={result.markdown_path}"
    )


if __name__ == "__main__":
    main()
