from __future__ import annotations

import unittest
from datetime import date

from quant_platform.services.yfinance_history import _derive_initial_history_start, _full_history_start


class YFinanceHistoryTest(unittest.TestCase):
    def test_initial_history_start_uses_configured_year_window(self) -> None:
        self.assertEqual(_derive_initial_history_start(date(2026, 4, 28), 10), date(2016, 4, 27))

    def test_full_history_start_is_intentionally_early(self) -> None:
        self.assertEqual(_full_history_start(), date(1900, 1, 1))


if __name__ == "__main__":
    unittest.main()
