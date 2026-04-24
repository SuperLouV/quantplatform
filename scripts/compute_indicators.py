"""Compute technical indicators from local processed OHLCV parquet."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from quant_platform.indicators import IndicatorEngine


def main() -> None:
    parser = argparse.ArgumentParser(description="Compute local technical indicators for one symbol.")
    parser.add_argument("symbol", help="Ticker symbol, for example AAPL")
    parser.add_argument(
        "--provider",
        default="yfinance",
        help="Processed data provider directory, default yfinance",
    )
    parser.add_argument(
        "--data-root",
        default="data/processed",
        help="Processed data root, default data/processed",
    )
    parser.add_argument(
        "--tail",
        type=int,
        default=5,
        help="Number of final rows to print from the indicator series",
    )
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parents[1]
    path = project_root / args.data_root / args.provider / "bars" / f"{args.symbol.upper()}.parquet"
    if not path.exists():
        raise FileNotFoundError(f"Processed bars not found: {path}")

    result = IndicatorEngine().compute_from_parquet(path)
    print(json.dumps({"symbol": args.symbol.upper(), "latest": result.latest}, ensure_ascii=False, indent=2))

    display_columns = ["timestamp", "close", *result.latest.keys()]
    available_columns = [column for column in display_columns if column in result.series.columns]
    print(result.series[available_columns].tail(args.tail).to_string(index=False))


if __name__ == "__main__":
    main()
