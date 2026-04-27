from __future__ import annotations

import unittest
from datetime import datetime

from quant_platform.market_calendar.us_market import (
    is_us_market_early_close,
    is_us_market_session,
    latest_completed_us_session,
)
from quant_platform.time_utils import US_EASTERN


class MarketCalendarTest(unittest.TestCase):
    def test_holidays_are_not_sessions(self) -> None:
        self.assertFalse(is_us_market_session(datetime(2026, 4, 3).date()))
        self.assertFalse(is_us_market_session(datetime(2026, 12, 25).date()))

    def test_early_close_day(self) -> None:
        self.assertTrue(is_us_market_early_close(datetime(2026, 11, 27).date()))

    def test_latest_completed_session_waits_for_data_delay(self) -> None:
        before_data_ready = datetime(2026, 4, 27, 16, 30, tzinfo=US_EASTERN)
        after_data_ready = datetime(2026, 4, 27, 18, 0, tzinfo=US_EASTERN)

        self.assertEqual(latest_completed_us_session(before_data_ready), datetime(2026, 4, 24).date())
        self.assertEqual(latest_completed_us_session(after_data_ready), datetime(2026, 4, 27).date())


if __name__ == "__main__":
    unittest.main()
