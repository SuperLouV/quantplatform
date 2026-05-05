from __future__ import annotations

import unittest
from datetime import date

from quant_platform.options.screenshot_parser import extract_option_quotes_from_text


class OptionScreenshotParserTest(unittest.TestCase):
    def test_extracts_labeled_option_quote_rows(self) -> None:
        text = """
        2026-06-19 CALL strike 300 bid 2.10 ask 2.30
        PUT strike 250 bid 1.80 ask 2.00
        """

        extraction = extract_option_quotes_from_text(text)

        self.assertEqual(len(extraction.contracts), 2)
        first = extraction.contracts[0]
        self.assertEqual(first.option_type, "call")
        self.assertEqual(first.expiration, date(2026, 6, 19))
        self.assertEqual(first.strike, 300)
        self.assertEqual(first.bid, 2.10)
        self.assertEqual(first.ask, 2.30)
        second = extraction.contracts[1]
        self.assertEqual(second.option_type, "put")
        self.assertEqual(second.expiration, date(2026, 6, 19))
        self.assertTrue(any("到期日来自前文" in item for item in second.confidence_notes))


if __name__ == "__main__":
    unittest.main()
