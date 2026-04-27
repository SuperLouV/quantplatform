from __future__ import annotations

import unittest
from datetime import date

from quant_platform.services.daily_report import _refresh_history_counts, _report_market_date


class DailyReportTest(unittest.TestCase):
    def test_report_date_falls_back_to_latest_cursor_when_refresh_has_no_success(self) -> None:
        summary = {
            "market_date_us": "2026-04-27",
            "history": {
                "AAPL": {"status": "empty", "cursor": "2026-04-24"},
                "MSFT": {"status": "empty", "cursor": "2026-04-24"},
            },
        }

        self.assertEqual(_report_market_date(summary, None), date(2026, 4, 24))

    def test_explicit_report_date_wins(self) -> None:
        summary = {"market_date_us": "2026-04-27", "history": {}}

        self.assertEqual(_report_market_date(summary, date(2026, 4, 23)), date(2026, 4, 23))

    def test_refresh_history_counts(self) -> None:
        summary = {
            "history": {
                "AAPL": {"status": "success"},
                "MSFT": {"status": "empty"},
                "NVDA": {"status": "error"},
            }
        }

        self.assertEqual(_refresh_history_counts(summary), {"success": 1, "empty": 1, "error": 1})


if __name__ == "__main__":
    unittest.main()
