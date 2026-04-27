from __future__ import annotations

import unittest

import pandas as pd

from quant_platform.indicators.engine import IndicatorEngine


class IndicatorEngineTest(unittest.TestCase):
    def test_strategy_v1_columns_are_computed(self) -> None:
        rows = 260
        frame = pd.DataFrame(
            {
                "timestamp": pd.date_range("2025-01-01", periods=rows, freq="B", tz="UTC"),
                "open": [float(100 + index) for index in range(rows)],
                "high": [float(101 + index) for index in range(rows)],
                "low": [float(99 + index) for index in range(rows)],
                "close": [float(100 + index) for index in range(rows)],
                "volume": [1_000_000 + index * 1000 for index in range(rows)],
            }
        )

        computation = IndicatorEngine().compute(frame)

        for key in (
            "ret_20d_skip5",
            "ret_60d_skip5",
            "ret_120d_skip5",
            "rsi_14_delta_5d",
            "volume_zscore_60",
            "trend_distance_sma50_atr14",
        ):
            self.assertIn(key, computation.latest)
            self.assertIsNotNone(computation.latest[key])

        latest_close = frame.iloc[-6]["close"]
        base_close = frame.iloc[-26]["close"]
        self.assertAlmostEqual(computation.latest["ret_20d_skip5"], latest_close / base_close - 1)


if __name__ == "__main__":
    unittest.main()
