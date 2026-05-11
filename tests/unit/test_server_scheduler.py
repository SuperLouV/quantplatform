from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from quant_platform.config import AppConfig, DataConfig, SchedulerConfig, Settings, StorageConfig
from quant_platform.services.server_scheduler import DailyRefreshScheduler, _is_fresh_completed_market_date


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

    def test_scheduler_skips_when_beijing_run_maps_to_weekend_us_date(self) -> None:
        monday_beijing = datetime(2026, 5, 11, 6, 30, tzinfo=ZoneInfo("Asia/Shanghai"))

        self.assertFalse(_is_fresh_completed_market_date(monday_beijing, date(2026, 5, 8)))

    def test_scheduler_runs_when_beijing_run_maps_to_completed_us_session(self) -> None:
        saturday_beijing = datetime(2026, 5, 9, 6, 30, tzinfo=ZoneInfo("Asia/Shanghai"))

        self.assertTrue(_is_fresh_completed_market_date(saturday_beijing, date(2026, 5, 8)))


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
