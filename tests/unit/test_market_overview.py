from __future__ import annotations

import unittest

from quant_platform.services.market_overview import MarketInstrumentState, _risk_state, _vix_state


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


if __name__ == "__main__":
    unittest.main()
