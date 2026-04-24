"""Update local market-wide event calendar history."""

from __future__ import annotations

import argparse
from datetime import date

from quant_platform.config import load_settings
from quant_platform.services.market_events import MarketEventService


def main() -> None:
    parser = argparse.ArgumentParser(description="Update market-wide event calendar history.")
    parser.add_argument("--start", help="Start date YYYY-MM-DD")
    parser.add_argument("--end", help="End date YYYY-MM-DD")
    parser.add_argument("--settings", default="config/settings.example.yaml")
    args = parser.parse_args()

    settings = load_settings(args.settings)
    service = MarketEventService(settings)
    result = service.update_events(
        start=date.fromisoformat(args.start) if args.start else None,
        end=date.fromisoformat(args.end) if args.end else None,
    )
    print(f"path={result.path}")
    print(f"events={len(result.events)}")
    print(f"provider_counts={result.provider_counts}")


if __name__ == "__main__":
    main()
