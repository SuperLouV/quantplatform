"""Fetch latest quote-like snapshot data for all symbols in a stock pool."""

from __future__ import annotations

import argparse
from pathlib import Path

from quant_platform.config import load_settings
from quant_platform.services import StockSnapshotBatchService


def main() -> None:
    parser = argparse.ArgumentParser(description="Update latest stock snapshots for a pool JSON file.")
    parser.add_argument(
        "--pool",
        default="data/reference/system/stock_pools/index/nasdaq100.json",
        help="Path to the stock pool JSON file",
    )
    parser.add_argument("--workers", type=int, default=8, help="Concurrent worker count")
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parents[1]
    settings = load_settings(project_root / "config" / "settings.example.yaml")
    service = StockSnapshotBatchService(settings)
    pool = service.load_pool(project_root / args.pool)
    snapshot_paths, dashboard_path = service.update_pool(pool, max_workers=args.workers)

    print(f"pool_id={pool.pool_id}")
    print(f"snapshot_count={len(snapshot_paths)}")
    print(f"dashboard_path={dashboard_path}")


if __name__ == "__main__":
    main()
