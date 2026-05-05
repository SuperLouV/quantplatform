"""Sync real Longbridge positions/watchlists into local stock pool artifacts."""

from __future__ import annotations

import argparse
from pathlib import Path

from quant_platform.config import load_settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Build local stock pools from read-only Longbridge positions and watchlists.")
    parser.parse_args()

    project_root = Path(__file__).resolve().parents[1]
    settings = load_settings(project_root / "config" / "settings.example.yaml")

    from quant_platform.services import LongbridgeStockPoolService

    result = LongbridgeStockPoolService(settings).sync()
    print(
        "SUCCESS longbridge-pool-sync "
        f"positions={result.position_count} "
        f"watchlist={result.watchlist_count} "
        f"combined={result.combined_count} "
        f"excluded={result.excluded_count} "
        f"core_pool={result.pool_paths['longbridge_core']} "
        f"metadata={result.metadata_path}"
    )


if __name__ == "__main__":
    main()
