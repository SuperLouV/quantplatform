from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from quant_platform.config import AIConfig, AppConfig, DataConfig, SchedulerConfig, Settings, StorageConfig
from quant_platform.services.ai_analysis import AutomatedAIAnalysisService


class AutomatedAIAnalysisServiceTest(unittest.TestCase):
    def test_analyze_dashboard_writes_json_and_markdown_without_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = _settings(root)
            dashboard = settings.storage.reference_dir / "system" / "dashboard_data.json"
            dashboard.parent.mkdir(parents=True)
            dashboard.write_text(
                json.dumps(
                    {
                        "snapshots": [
                            {
                                "symbol": "AAPL",
                                "pool_ids": ["longbridge_core"],
                                "current_price": 280,
                                "latest_close": 279,
                                "quote_provider_status": "success",
                                "screening_status": "ready",
                                "indicators": {
                                    "sma_20": 260,
                                    "sma_50": 250,
                                    "rsi_14": 58,
                                    "macd_histogram": 1.2,
                                    "atr_14": 5,
                                    "volume_ratio_20": 1.1,
                                },
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            result = AutomatedAIAnalysisService(settings).analyze_dashboard(use_model=False)

            self.assertEqual(result.snapshot_count, 1)
            self.assertEqual(result.model_status, "skipped")
            self.assertTrue(result.json_path.exists())
            self.assertTrue(result.markdown_path.exists())
            payload = json.loads(result.json_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["analyses"][0]["result"]["target_id"], "AAPL")
            self.assertEqual(payload["analyses"][0]["structured_report"]["technical_interpretation"]["state"], "偏强")


def _settings(root: Path) -> Settings:
    return Settings(
        app=AppConfig(name="test", env="test"),
        data=DataConfig(provider="yfinance", timezone="America/New_York"),
        storage=StorageConfig(
            raw_dir=root / "data" / "raw",
            processed_dir=root / "data" / "processed",
            reference_dir=root / "data" / "reference",
            cache_dir=root / "data" / "cache",
            state_db=root / "data" / "system" / "state.db",
        ),
        scheduler=SchedulerConfig(),
        ai=AIConfig(provider="none"),
    )


if __name__ == "__main__":
    unittest.main()
