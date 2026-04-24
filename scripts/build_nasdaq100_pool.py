"""Create a dedicated Nasdaq-100 stock pool file."""

from __future__ import annotations

from pathlib import Path

from quant_platform.config import load_settings
from quant_platform.services import Nasdaq100PoolService


def main() -> None:
    project_root = Path(__file__).resolve().parents[1]
    settings = load_settings(project_root / "config" / "settings.example.yaml")
    service = Nasdaq100PoolService(settings)
    pool = service.build_pool()
    path = service.write_pool(pool)
    print(f"pool_id={pool.pool_id}")
    print(f"symbol_count={len(pool.symbols)}")
    print(f"path={path}")


if __name__ == "__main__":
    main()
