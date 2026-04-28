from __future__ import annotations

import unittest
from datetime import date
from tempfile import TemporaryDirectory
from pathlib import Path

import pandas as pd

from quant_platform.config import AppConfig, DataConfig, SchedulerConfig, Settings, StorageConfig
from quant_platform.services.market_overview import MarketInstrumentState, _risk_state, _vix_state
from quant_platform.services.market_overview import MarketOverviewService


def _state(symbol: str, close: float, distance_sma50_pct: float, status: str = "ok") -> MarketInstrumentState:
    return MarketInstrumentState(
        symbol=symbol,
        name=symbol,
        latest_date_us="2026-04-24",
        close=close,
        change_1d_pct=0,
        change_5d_pct=0,
        change_20d_pct=0,
        sma50=close,
        distance_sma50_pct=distance_sma50_pct,
        rsi14=50,
        trend_state="强于 SMA50",
        data_status=status,
    )


class MarketOverviewTest(unittest.TestCase):
    def test_vix_state_buckets(self) -> None:
        self.assertIn("正常区间", _vix_state(_state("^VIX", 18, -10)))
        self.assertIn("警戒区间", _vix_state(_state("^VIX", 21, -10)))
        self.assertIn("高风险区间", _vix_state(_state("^VIX", 26, -10)))
        self.assertIn("恐慌区间", _vix_state(_state("^VIX", 31, -10)))

    def test_risk_state_prioritizes_high_vix(self) -> None:
        spy = _state("SPY", 500, 5)
        qqq = _state("QQQ", 500, 5)
        high_vix = _state("^VIX", 26, 10)

        self.assertIn("Risk Off", _risk_state(spy, qqq, high_vix))

    def test_risk_state_allows_risk_on_when_spy_is_above_sma50_and_vix_normal(self) -> None:
        spy = _state("SPY", 500, 5)
        qqq = _state("QQQ", 500, 5)
        normal_vix = _state("^VIX", 18, -10)

        self.assertIn("Risk On", _risk_state(spy, qqq, normal_vix))

    def test_build_marks_stale_market_proxy_data(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bars_dir = root / "processed" / "yfinance" / "bars"
            bars_dir.mkdir(parents=True)
            frame = pd.DataFrame(
                {
                    "timestamp": pd.date_range("2025-01-01", periods=260, freq="B", tz="UTC"),
                    "open": [100 + index for index in range(260)],
                    "high": [101 + index for index in range(260)],
                    "low": [99 + index for index in range(260)],
                    "close": [100 + index for index in range(260)],
                    "volume": [1_000_000 for _ in range(260)],
                }
            )
            frame.to_parquet(bars_dir / "SPY.parquet", index=False)

            settings = Settings(
                app=AppConfig(name="test", env="test"),
                data=DataConfig(provider="yfinance", timezone="America/New_York", request_min_interval_seconds=0),
                storage=StorageConfig(
                    raw_dir=root / "raw",
                    processed_dir=root / "processed",
                    reference_dir=root / "reference",
                    cache_dir=root / "cache",
                    state_db=root / "state" / "state.db",
                ),
                scheduler=SchedulerConfig(enabled=False),
            )

            overview = MarketOverviewService(settings).build(
                market_date_us=date(2026, 4, 27),
                generated_at_beijing="test",
            )

        spy = next(item for item in overview.indexes if item.symbol == "SPY")
        self.assertEqual(spy.data_status, "stale_local_bars")
        self.assertIn("SPY", overview.summary["missing_indexes"])


if __name__ == "__main__":
    unittest.main()
