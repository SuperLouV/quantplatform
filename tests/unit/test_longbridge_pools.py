from __future__ import annotations

import unittest

from quant_platform.services.longbridge_pools import normalize_longbridge_pool_inputs


class LongbridgePoolsTest(unittest.TestCase):
    def test_normalize_positions_and_watchlists_filters_indexes_and_options(self) -> None:
        positions_payload = [
            {"symbol": "AAPL.US", "quantity": "10", "cost_price": "180.5", "currency": "USD"},
            {"symbol": ".VIX.US", "quantity": "1", "type": "Index"},
            {"symbol": "AAPL260515C250000.US", "quantity": "1", "type": "Option"},
            {"symbol": "700.HK", "quantity": "2"},
        ]
        watchlists_payload = [
            {
                "name": "AI",
                "securities": [
                    {"symbol": "NVDA.US", "name": "NVIDIA"},
                    {"symbol": "AAPL.US", "name": "Apple"},
                    {"symbol": ".IXIC.US", "type": "Index"},
                ],
            },
            {"name": "Defensive", "symbols": ["MSFT.US"]},
        ]

        positions, watchlist, excluded = normalize_longbridge_pool_inputs(
            positions_payload=positions_payload,
            watchlists_payload=watchlists_payload,
        )

        self.assertEqual([item.symbol for item in positions], ["AAPL"])
        self.assertEqual(positions[0].quantity, 10)
        self.assertEqual(positions[0].cost_price, 180.5)
        watchlist_by_symbol = {item.symbol: item for item in watchlist}
        self.assertEqual(sorted(watchlist_by_symbol), ["AAPL", "MSFT", "NVDA"])
        self.assertEqual(watchlist_by_symbol["NVDA"].watchlist_groups, ["AI"])
        self.assertEqual(watchlist_by_symbol["MSFT"].watchlist_groups, ["Defensive"])
        self.assertGreaterEqual(len(excluded), 3)


if __name__ == "__main__":
    unittest.main()
