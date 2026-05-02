from __future__ import annotations

import unittest
from datetime import date

from quant_platform.options import AccountProfile, OptionContract, OptionsAssistantService, OptionStrategyRequest, StockOptionContext


class OptionsAssistantTest(unittest.TestCase):
    def test_cash_secured_put_rejects_contract_that_exceeds_small_account(self) -> None:
        request = OptionStrategyRequest(
            strategy="cash_secured_put",
            account=AccountProfile(equity=5_000, cash=5_000, max_cash_per_trade_pct=0.4),
            stock=StockOptionContext(symbol="TSM", current_price=140, as_of=date(2026, 5, 1), support_price=130),
            contract=OptionContract(
                symbol="TSM",
                option_type="put",
                strike=130,
                expiration=date(2026, 6, 19),
                bid=2.0,
                ask=2.2,
                delta=-0.24,
                open_interest=500,
            ),
        )

        result = OptionsAssistantService().evaluate(request)

        self.assertEqual(result.decision, "不适合")
        self.assertEqual(result.capital_required, 13_000)
        self.assertTrue(any("超过当前现金" in item for item in result.violations))

    def test_cash_secured_put_can_pass_basic_low_price_contract(self) -> None:
        request = OptionStrategyRequest(
            strategy="cash_secured_put",
            account=AccountProfile(equity=5_000, cash=5_000, max_cash_per_trade_pct=0.5),
            stock=StockOptionContext(symbol="XYZ", current_price=25, as_of=date(2026, 5, 1), support_price=23),
            contract=OptionContract(
                symbol="XYZ",
                option_type="put",
                strike=20,
                expiration=date(2026, 6, 19),
                bid=0.5,
                ask=0.55,
                delta=-0.2,
                open_interest=300,
            ),
        )

        result = OptionsAssistantService().evaluate(request)

        self.assertEqual(result.decision, "符合策略")
        self.assertEqual(result.capital_required, 2_000)
        self.assertAlmostEqual(result.breakeven or 0, 19.475)

    def test_covered_call_requires_one_hundred_shares(self) -> None:
        request = OptionStrategyRequest(
            strategy="covered_call",
            account=AccountProfile(equity=5_000, cash=500, stock_shares=20, stock_cost_basis=20),
            stock=StockOptionContext(symbol="XYZ", current_price=25, as_of=date(2026, 5, 1)),
            contract=OptionContract(
                symbol="XYZ",
                option_type="call",
                strike=30,
                expiration=date(2026, 6, 19),
                bid=0.4,
                ask=0.45,
                delta=0.2,
                open_interest=300,
            ),
        )

        result = OptionsAssistantService().evaluate(request)

        self.assertEqual(result.decision, "不适合")
        self.assertTrue(any("至少持有 100 股" in item for item in result.violations))


if __name__ == "__main__":
    unittest.main()
