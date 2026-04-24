"""Initialize local data directories and the SQLite state ledger."""

from __future__ import annotations

from pathlib import Path

from quant_platform.config import load_settings
from quant_platform.services import bootstrap_local_state


def main() -> None:
    project_root = Path(__file__).resolve().parents[1]
    settings = load_settings(project_root / "config" / "settings.example.yaml")
    artifacts = bootstrap_local_state(settings)

    print(f"initialized raw_dir={artifacts.layout.storage.raw_dir}")
    print(f"initialized processed_dir={artifacts.layout.storage.processed_dir}")
    print(f"initialized reference_dir={artifacts.layout.storage.reference_dir}")
    print(f"initialized cache_dir={artifacts.layout.storage.cache_dir}")
    print(f"initialized state_db={artifacts.state_store.path}")


if __name__ == "__main__":
    main()
