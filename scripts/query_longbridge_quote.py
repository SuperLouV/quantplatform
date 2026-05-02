"""Query a Longbridge CLI quote and print the normalized snapshot payload."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from quant_platform.clients import LongbridgeCLIClient
from quant_platform.config import load_settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch a read-only quote through the local Longbridge CLI.")
    parser.add_argument("symbol", help="US symbol, e.g. AAPL or AAPL.US")
    parser.add_argument("--config", default="config/settings.example.yaml")
    parser.add_argument("--raw", action="store_true", help="Print raw Longbridge CLI payload instead of normalized snapshot.")
    args = parser.parse_args()

    settings = load_settings(PROJECT_ROOT / args.config)
    client = LongbridgeCLIClient.from_data_config(settings.data)
    payload = client.fetch_quote(args.symbol) if args.raw else client.fetch_quote_snapshot(args.symbol)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
