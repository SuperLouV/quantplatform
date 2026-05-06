from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from quant_platform.config import AppConfig, DataConfig, SchedulerConfig, Settings, StorageConfig
from quant_platform.services.server_scheduler import DailyRefreshScheduler


class DailyRefreshSchedulerTest(unittest.TestCase):
    def test_summary_complete_ignores_optional_supplemental_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scheduler = DailyRefreshScheduler(_settings(root), project_root=root)
            summary_path = root / "data" / "reference" / "system" / "daily_refresh" / "core_2026-05-05.json"
            summary_path.parent.mkdir(parents=True)
            summary_path.write_text(
                json.dumps(
                    {
                        "market_date_us": "2026-05-05",
                        "pool_id": "core",
                        "snapshot_count": 1,
                        "history": {
                            "AAPL": {"status": "success"},
                            "TSLA": {"status": "error", "error": "provider unavailable"},
                        },
                        "supplemental_outputs": {},
                    }
                ),
                encoding="utf-8",
            )

            self.assertTrue(scheduler._summary_is_complete(summary_path))

    def test_summary_incomplete_without_successful_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scheduler = DailyRefreshScheduler(_settings(root), project_root=root)
            summary_path = root / "data" / "reference" / "system" / "daily_refresh" / "core_2026-05-05.json"
            summary_path.parent.mkdir(parents=True)
            summary_path.write_text(
                json.dumps(
                    {
                        "market_date_us": "2026-05-05",
                        "pool_id": "core",
                        "snapshot_count": 0,
                        "history": {"AAPL": {"status": "error", "error": "provider unavailable"}},
                        "supplemental_outputs": {"daily_report": {"status": "success"}},
                    }
                ),
                encoding="utf-8",
            )

            self.assertFalse(scheduler._summary_is_complete(summary_path))


def _settings(root: Path) -> Settings:
    return Settings(
        app=AppConfig(name="test", env="test"),
        data=DataConfig(provider="yfinance", timezone="America/New_York", request_min_interval_seconds=0),
        storage=StorageConfig(
            raw_dir=root / "data" / "raw",
            processed_dir=root / "data" / "processed",
            reference_dir=root / "data" / "reference",
            cache_dir=root / "data" / "cache",
            state_db=root / "data" / "system" / "state.db",
        ),
        scheduler=SchedulerConfig(),
    )


if __name__ == "__main__":
    unittest.main()
