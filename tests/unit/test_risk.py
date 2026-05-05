from __future__ import annotations

import unittest
from datetime import date

from quant_platform.portfolio import AccountPosition, AccountSnapshot
from quant_platform.risk import PortfolioRiskAnalyzer, RiskPolicy


class PortfolioRiskAnalyzerTest(unittest.TestCase):
    def test_assess_concentration_atr_pdt_and_events(self) -> None:
        account = AccountSnapshot(
            provider="test",
            generated_at_beijing="2026-05-05T10:00:00+08:00",
            net_assets=20_000,
            available_cash=2_000,
            positions=[
                AccountPosition(symbol="AAPL.US", name="Apple", quantity=20, cost_price=180, market_price=200, market_value=4_000),
                AccountPosition(symbol="MSFT.US", name="Microsoft", quantity=10, cost_price=300, market_price=310, market_value=3_100),
            ],
        )
        snapshots = {
            "AAPL": {
                "sector": "Technology",
                "next_earnings_date": "2026-05-08",
                "indicators": {"atr_14": 5},
            },
            "MSFT": {"sector": "Technology", "indicators": {"atr_14": 4}},
        }
        assessment = PortfolioRiskAnalyzer(RiskPolicy(max_position_weight=0.10, max_sector_weight=0.25)).assess(
            account,
            snapshots_by_symbol=snapshots,
            market_events=[
                {
                    "event_time": "2026-05-07T12:30:00+00:00",
                    "importance": "high",
                    "title": "CPI",
                    "source": "fred",
                }
            ],
            as_of=date(2026, 5, 5),
        )

        self.assertEqual(assessment.pdt.status, "watch")
        self.assertEqual(len(assessment.event_risks), 2)
        self.assertEqual(assessment.sector_exposures[0].status, "breach")
        self.assertEqual(assessment.positions[0].concentration_status, "breach")
        self.assertAlmostEqual(assessment.positions[0].atr_stop.stop_price or 0, 190)
        self.assertLess(assessment.health_score, 100)

    def test_sector_fallbacks_cover_etfs_and_class_share_symbols(self) -> None:
        account = AccountSnapshot(
            provider="test",
            generated_at_beijing="2026-05-05T10:00:00+08:00",
            net_assets=20_000,
            positions=[
                AccountPosition(symbol="VOO.US", quantity=2, market_price=500, market_value=1_000),
                AccountPosition(symbol="BRK.B.US", quantity=1, market_price=400, market_value=400),
                AccountPosition(symbol="CRCL.US", quantity=10, cost_price=40, market_price=84, market_value=840),
            ],
        )

        assessment = PortfolioRiskAnalyzer().assess(
            account,
            snapshots_by_symbol={
                "VOO": {"indicators": {"atr_14": 4}},
                "BRK.B": {"indicators": {"atr_14": 3}},
                "CRCL": {"indicators": {"atr_14": 6}},
            },
            as_of=date(2026, 5, 5),
        )

        by_symbol = {item.symbol: item for item in assessment.positions}
        self.assertEqual(by_symbol["VOO"].sector, "美国大盘 ETF")
        self.assertEqual(by_symbol["BRK.B"].sector, "金融/保险控股")
        self.assertEqual(by_symbol["CRCL"].sector, "金融科技")
        self.assertAlmostEqual(by_symbol["CRCL"].unrealized_pl_pct or 0, 110)
        self.assertTrue(any("成本盈亏" in flag for flag in by_symbol["CRCL"].flags))


if __name__ == "__main__":
    unittest.main()
