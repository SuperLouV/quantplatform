"""Build stock pools from manual themes, system seeds, and future AI candidates."""

from __future__ import annotations

from pathlib import Path

from quant_platform.config import load_settings
from quant_platform.screeners import load_universe_config
from quant_platform.services import UniverseService


def main() -> None:
    project_root = Path(__file__).resolve().parents[1]
    settings = load_settings(project_root / "config" / "settings.example.yaml")
    universe_config = load_universe_config(project_root / "config" / "universe.example.yaml")
    service = UniverseService(settings)
    pools = service.build_from_config(universe_config)
    first_output_path = service.write_snapshot(pools)

    for pool in pools:
        print(f"{pool.pool_id}={len(pool.members)}")
    print(f"first_snapshot_path={first_output_path}")


if __name__ == "__main__":
    main()
