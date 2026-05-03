from __future__ import annotations

import unittest
from datetime import date

from quant_platform.options import AccountProfile, OptionsAssistantService, SellPutScanConfig


class OptionsScannerTest(unittest.TestCase):
    def test_sell_put_scan_runs_without_quote_access(self) -> None:
        result = OptionsAssistantService().scan_sell_put(
            symbol="AAPL",
            underlying_price=280,
            as_of=date(2026, 5, 1),
            account=AccountProfile(equity=50_000, cash=50_000, max_cash_per_trade_pct=0.6),
            expirations=[date(2026, 5, 15)],
            chains_by_expiration={
                date(2026, 5, 15): [
                    {"strike": "270", "put_symbol": "AAPL260515P270000.US", "standard": "true"},
                    {"strike": "250", "put_symbol": "AAPL260515P250000.US", "standard": "true"},
                    {"strike": "200", "put_symbol": "AAPL260515P200000.US", "standard": "true"},
                ]
            },
            option_volume_payload={"c": "1000", "p": "500"},
            config=SellPutScanConfig(min_dte=7, max_dte=30, min_otm_pct=0.02, max_otm_pct=0.20, max_cash_per_trade_pct=0.6),
        )

        payload = result.to_dict()

        self.assertEqual(payload["candidate_count"], 2)
        first = payload["candidates"][0]
        self.assertEqual(first["put_symbol"], "AAPL260515P250000.US")
        self.assertTrue(first["quote_required"])
        self.assertEqual(first["quote_access"], "missing")
        self.assertEqual(first["option_volume"]["put_call_ratio"], 0.5)
        self.assertTrue(any("缺少具体合约实时 bid/ask" in item for item in first["warnings"]))

    def test_sell_put_scan_blocks_contract_that_exceeds_cash(self) -> None:
        result = OptionsAssistantService().scan_sell_put(
            symbol="AAPL",
            underlying_price=280,
            as_of=date(2026, 5, 1),
            account=AccountProfile(equity=5_000, cash=5_000),
            expirations=[date(2026, 5, 15)],
            chains_by_expiration={
                date(2026, 5, 15): [
                    {"strike": "250", "put_symbol": "AAPL260515P250000.US", "standard": "true"},
                ]
            },
            config=SellPutScanConfig(min_dte=7, max_dte=30, min_otm_pct=0.02, max_otm_pct=0.20),
        )

        candidate = result.candidates[0]

        self.assertEqual(candidate.status, "blocked")
        self.assertTrue(any("超过当前现金" in item for item in candidate.warnings))


if __name__ == "__main__":
    unittest.main()
