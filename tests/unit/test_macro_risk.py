from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

import pandas as pd

from quant_platform.config import AppConfig, DataConfig, SchedulerConfig, Settings, StorageConfig
from quant_platform.services.macro_risk import MacroRiskService, _find_temperature_value, _optional_float


class MacroRiskServiceTest(unittest.TestCase):
    def test_optional_float_rejects_nan_and_inf(self) -> None:
        self.assertIsNone(_optional_float("nan"))
        self.assertIsNone(_optional_float("inf"))
        self.assertIsNone(_optional_float("-inf"))
        self.assertEqual(_optional_float("42.5"), 42.5)

    def test_temperature_value_skips_non_finite_values(self) -> None:
        payload = {"score": "nan", "nested": {"temperature": "80"}}
        self.assertEqual(_find_temperature_value(payload), 80)

    def test_generate_writes_read_only_macro_risk_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = _settings(root)
            _write_bars(settings, "SPY", close=500)
            _write_bars(settings, "QQQ", close=520)
            _write_bars(settings, "DIA", close=430)
            _write_bars(settings, "^VIX", close=18, daily_step=0)

            result = MacroRiskService(settings, longbridge_client=_FakeLongbridgeClient()).generate(
                market_date_us=date(2026, 5, 5),
                symbols=["AAPL", "AAPL.US"],
                news_limit_per_symbol=3,
            )

            payload = json.loads(result.json_path.read_text(encoding="utf-8"))
            self.assertEqual(result.risk_state, "caution_overheated")
            self.assertEqual(payload["execution_boundary"], "read_only_macro_news_risk_no_auto_order")
            self.assertEqual(payload["sentiment_state"], "overheated")
            self.assertEqual(len(payload["news_items"]), 1)
            self.assertTrue(result.markdown_path.exists())


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
        scheduler=SchedulerConfig(enabled=False),
    )


def _write_bars(settings: Settings, symbol: str, *, close: float, daily_step: float = 0.2) -> None:
    path = settings.storage.processed_dir / "yfinance" / "bars" / f"{symbol}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    timestamps = pd.bdate_range(end="2026-05-05", periods=260, tz="UTC") + pd.Timedelta(hours=21)
    closes = [close + (index * daily_step) for index in range(len(timestamps))]
    frame = pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": [value - 0.5 for value in closes],
            "high": [value + 1 for value in closes],
            "low": [value - 1 for value in closes],
            "close": closes,
            "volume": [1_000_000 for _ in closes],
        }
    )
    frame.to_parquet(path, index=False)


class _FakeLongbridgeClient:
    def fetch_market_temperature(self) -> dict[str, object]:
        return {"score": "nan", "nested": {"temperature": "82"}}

    def fetch_news(self, symbol: str, *, limit: int = 5) -> list[dict[str, object]]:
        return [{"id": "n1", "title": f"{symbol} headline", "source": "Longbridge", "published_at": "2026-05-05"}]


if __name__ == "__main__":
    unittest.main()
