"""Create curated preset pools for the local dashboard."""

from __future__ import annotations

from pathlib import Path

from quant_platform.config import load_settings
from quant_platform.services import PresetPoolService


def main() -> None:
    project_root = Path(__file__).resolve().parents[1]
    settings = load_settings(project_root / "config" / "settings.example.yaml")
    service = PresetPoolService(settings)
    pools = service.build_pools()
    paths = service.write_pools(pools)
    print(f"pool_count={len(paths)}")
    for path in paths:
        print(path)


if __name__ == "__main__":
    main()
