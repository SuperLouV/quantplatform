from __future__ import annotations

import unittest
from datetime import date

from quant_platform.services.daily_report import _history_coverage_summary, _refresh_history_counts, _report_market_date


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

    def test_history_coverage_summary_uses_successful_symbols(self) -> None:
        summary = {
            "history": {
                "AAPL": {"status": "success", "earliest_date": "1980-12-12", "latest_date": "2026-04-27", "total_rows": 11400},
                "MSFT": {"status": "success", "earliest_date": "1986-03-13", "latest_date": "2026-04-27", "total_rows": 10100},
                "BAD": {"status": "error", "earliest_date": "1970-01-01", "latest_date": "1970-01-02", "total_rows": 2},
            }
        }

        self.assertEqual(
            _history_coverage_summary(summary),
            {"earliest_date": "1980-12-12", "latest_date": "2026-04-27", "min_rows": 10100},
        )


if __name__ == "__main__":
    unittest.main()
