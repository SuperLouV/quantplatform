from __future__ import annotations

import unittest

from quant_platform.screeners.scanner import MarketScanner
from quant_platform.services.ui_data import _scanner_market_date_us


def _snapshot(symbol: str, ret20: float, ret60: float, ret120: float) -> dict[str, object]:
    return {
        "symbol": symbol,
        "current_price": 120,
        "previous_close": 118,
        "latest_history_date_us": "2026-04-24",
        "indicators": {
            "sma_20": 110,
            "sma_50": 100,
            "sma_200": 90,
            "rsi_14": 56,
            "rsi_14_delta_5d": 2,
            "macd": 2,
            "macd_signal": 1,
            "volume_zscore_60": 0.8,
            "trend_distance_sma50_atr14": 2,
            "ret_20d_skip5": ret20,
            "ret_60d_skip5": ret60,
            "ret_120d_skip5": ret120,
        },
    }


class MarketScannerTest(unittest.TestCase):
    def test_scan_snapshots_adds_momentum_rank_and_strategy_id(self) -> None:
        result = MarketScanner().scan_snapshots(
            [
                _snapshot("AAA", 0.2, 0.3, 0.4),
                _snapshot("BBB", 0.1, 0.2, 0.3),
                _snapshot("CCC", -0.1, -0.2, -0.3),
            ]
        )

        by_symbol = {item.symbol: item for item in result.candidates}
        self.assertEqual(result.summary.total, 3)
        self.assertEqual(by_symbol["AAA"].strategy_id, "trend_momentum_v1")
        self.assertEqual(by_symbol["AAA"].action, "候选买入")
        self.assertEqual(by_symbol["AAA"].momentum_rank_pct, 100.0)
        self.assertEqual(by_symbol["CCC"].momentum_rank_pct, 0.0)

    def test_missing_indicators_becomes_data_insufficient(self) -> None:
        candidate = MarketScanner().scan_snapshot({"symbol": "BAD"})

        self.assertEqual(candidate.action, "数据不足")
        self.assertEqual(candidate.risk_level, "高")

    def test_scanner_market_date_uses_latest_candidate_history_date(self) -> None:
        result = MarketScanner().scan_snapshots(
            [
                _snapshot("AAA", 0.2, 0.3, 0.4),
                {**_snapshot("BBB", 0.1, 0.2, 0.3), "latest_history_date_us": "2026-04-27"},
            ]
        )

        self.assertEqual(_scanner_market_date_us(result.candidates), "2026-04-27")


if __name__ == "__main__":
    unittest.main()
