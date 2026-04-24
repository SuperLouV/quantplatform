"""Detect standardized signals from local processed OHLCV parquet."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from quant_platform.indicators import IndicatorEngine, SignalDetector


def main() -> None:
    parser = argparse.ArgumentParser(description="Detect local rule-based signals for one symbol.")
    parser.add_argument("symbol", help="Ticker symbol, for example AAPL")
    parser.add_argument("--provider", default="yfinance", help="Processed data provider directory")
    parser.add_argument("--data-root", default="data/processed", help="Processed data root")
    args = parser.parse_args()

    symbol = args.symbol.upper()
    project_root = Path(__file__).resolve().parents[1]
    path = project_root / args.data_root / args.provider / "bars" / f"{symbol}.parquet"
    if not path.exists():
        raise FileNotFoundError(f"Processed bars not found: {path}")

    indicators = IndicatorEngine().compute_from_parquet(path)
    summary = SignalDetector().detect(symbol, indicators.series)
    payload = asdict(summary)
    if summary.as_of is not None:
        payload["as_of"] = summary.as_of.isoformat()
    for signal in payload["signals"]:
        signal["triggered_at"] = signal["triggered_at"].isoformat()
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
