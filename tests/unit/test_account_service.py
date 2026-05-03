from __future__ import annotations

import unittest

from quant_platform.services.account import normalize_longbridge_account


ASSETS = [
    {
        "buy_power": "8000.00",
        "cash_infos": [
            {
                "available_cash": "1200.00",
                "currency": "USD",
                "frozen_cash": "0.00",
                "settling_cash": "0.00",
                "withdraw_cash": "1200.00",
            }
        ],
        "currency": "USD",
        "net_assets": "10000.00",
        "risk_level": "Safe",
        "total_cash": "1200.00",
    }
]

PORTFOLIO = {
    "overview": {
        "total_asset": "10000.00",
        "market_cap": "8800.00",
        "total_cash": "1200.00",
        "total_pl": "500.00",
        "total_today_pl": "25.00",
        "risk_level": 0,
        "currency": "USD",
    },
    "holdings": [
        {
            "symbol": "AAPL.US",
            "name": "Apple",
            "currency": "USD",
            "quantity": "4",
            "available_quantity": "4",
            "cost_price": "250.00",
            "market_value": "1120.00",
            "market_price": "280.00",
            "prev_close": "270.00",
        }
    ],
}

POSITIONS = [
    {
        "available": "4",
        "cost_price": "250.00",
        "currency": "USD",
        "market": "US",
        "name": "Apple",
        "quantity": "4",
        "symbol": "AAPL.US",
    }
]


class AccountServiceTest(unittest.TestCase):
    def test_normalize_longbridge_account_for_options_assistant(self) -> None:
        snapshot = normalize_longbridge_account(
            assets_payload=ASSETS,
            portfolio_payload=PORTFOLIO,
            positions_payload=POSITIONS,
        )

        self.assertEqual(snapshot.provider, "longbridge_cli")
        self.assertEqual(snapshot.currency, "USD")
        self.assertEqual(snapshot.net_assets, 10000.0)
        self.assertEqual(snapshot.cash_for_cash_secured_put, 1200.0)
        self.assertEqual(len(snapshot.positions), 1)
        self.assertEqual(snapshot.position_for("AAPL").available_quantity, 4)

        account = snapshot.to_options_account("AAPL")
        self.assertEqual(account.equity, 10000.0)
        self.assertEqual(account.cash, 1200.0)
        self.assertEqual(account.stock_shares, 4)
        self.assertEqual(account.stock_cost_basis, 250.0)

    def test_to_dict_does_not_expose_buying_power_as_csp_cash(self) -> None:
        payload = normalize_longbridge_account(
            assets_payload=ASSETS,
            portfolio_payload=PORTFOLIO,
            positions_payload=POSITIONS,
        ).to_dict()

        self.assertEqual(payload["buy_power"], 8000.0)
        self.assertEqual(payload["cash_for_cash_secured_put"], 1200.0)
        self.assertEqual(payload["position_count"], 1)


if __name__ == "__main__":
    unittest.main()
