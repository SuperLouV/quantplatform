from __future__ import annotations

import json
import subprocess
import unittest
from datetime import date
from unittest.mock import patch

from quant_platform.clients.longbridge_cli import LongbridgeCLIClient, normalize_quote_snapshot, to_longbridge_symbol


RAW_AAPL_QUOTE = {
    "high": "287.220",
    "last": "280.140",
    "low": "278.370",
    "open": "278.855",
    "overnight_quote": None,
    "post_market_quote": {
        "high": "280.290",
        "last": "280.070",
        "low": "279.720",
        "prev_close": "280.140",
        "timestamp": "2026-05-01 23:59:59",
        "turnover": "1337301481.951",
        "volume": 4773935,
    },
    "pre_market_quote": {
        "high": "282.420",
        "last": "278.420",
        "low": "277.480",
        "prev_close": "271.350",
        "timestamp": "2026-05-01 13:30:01",
        "turnover": "436598133.444",
        "volume": 1556981,
    },
    "prev_close": "271.350",
    "status": "Normal",
    "symbol": "AAPL.US",
    "turnover": "22565781150.000",
    "volume": 79915442,
}


class LongbridgeCLITest(unittest.TestCase):
    def test_symbol_normalization_adds_us_suffix(self) -> None:
        self.assertEqual(to_longbridge_symbol("AAPL"), "AAPL.US")
        self.assertEqual(to_longbridge_symbol("AAPL.US"), "AAPL.US")

    def test_normalize_quote_snapshot_prefers_post_market_last(self) -> None:
        payload = normalize_quote_snapshot(RAW_AAPL_QUOTE, requested_symbol="AAPL")

        self.assertEqual(payload["symbol"], "AAPL")
        self.assertEqual(payload["provider"], "longbridge_cli")
        self.assertEqual(payload["regular_market_price"], 280.14)
        self.assertEqual(payload["current_price"], 280.07)
        self.assertEqual(payload["post_market_price"], 280.07)
        self.assertEqual(payload["pre_market_price"], 278.42)
        self.assertEqual(payload["market_state"], "POST")
        self.assertEqual(payload["latest_history_date_us"], "2026-05-01")
        self.assertEqual(payload["latest_volume"], 79_915_442)
        expected_change = ((280.07 - 271.35) / 271.35) * 100
        self.assertAlmostEqual(payload["change_percent"] or 0, expected_change)

    @patch("quant_platform.clients.longbridge_cli.subprocess.run")
    def test_fetch_quote_uses_longbridge_cli_json_output(self, run) -> None:
        run.return_value = subprocess.CompletedProcess(
            args=["longbridge"],
            returncode=0,
            stdout=json.dumps([RAW_AAPL_QUOTE]),
            stderr="",
        )

        payload = LongbridgeCLIClient(binary="longbridge", timeout_seconds=7).fetch_quote_snapshot("AAPL")

        run.assert_called_once()
        command = run.call_args.args[0]
        self.assertEqual(command, ["longbridge", "quote", "AAPL.US", "--format", "json"])
        self.assertEqual(run.call_args.kwargs["timeout"], 7)
        self.assertEqual(payload["symbol"], "AAPL")
        self.assertEqual(payload["current_price"], 280.07)

    @patch("quant_platform.clients.longbridge_cli.subprocess.run")
    def test_fetch_option_expirations_and_chain_use_read_only_commands(self, run) -> None:
        run.side_effect = [
            subprocess.CompletedProcess(
                args=["longbridge"],
                returncode=0,
                stdout=json.dumps([{"expiry_date": "2026-05-15"}]),
                stderr="",
            ),
            subprocess.CompletedProcess(
                args=["longbridge"],
                returncode=0,
                stdout=json.dumps(
                    [
                        {
                            "call_symbol": "AAPL260515C250000.US",
                            "put_symbol": "AAPL260515P250000.US",
                            "standard": "true",
                            "strike": "250",
                        }
                    ]
                ),
                stderr="",
            ),
        ]
        client = LongbridgeCLIClient(binary="longbridge", timeout_seconds=7)

        expirations = client.fetch_option_expirations("AAPL")
        chain = client.fetch_option_chain("AAPL", date(2026, 5, 15))

        self.assertEqual(expirations, [date(2026, 5, 15)])
        self.assertEqual(chain[0]["put_symbol"], "AAPL260515P250000.US")
        commands = [call.args[0] for call in run.call_args_list]
        self.assertEqual(commands[0], ["longbridge", "option", "chain", "AAPL.US", "--format", "json"])
        self.assertEqual(
            commands[1],
            ["longbridge", "option", "chain", "AAPL.US", "--date", "2026-05-15", "--format", "json"],
        )

    @patch("quant_platform.clients.longbridge_cli.subprocess.run")
    def test_fetch_option_volume(self, run) -> None:
        run.return_value = subprocess.CompletedProcess(
            args=["longbridge"],
            returncode=0,
            stdout=json.dumps({"c": "1869283", "p": "708902"}),
            stderr="",
        )

        payload = LongbridgeCLIClient(binary="longbridge", timeout_seconds=7).fetch_option_volume("AAPL")

        self.assertEqual(payload["c"], "1869283")
        self.assertEqual(payload["p"], "708902")
        self.assertEqual(run.call_args.args[0], ["longbridge", "option", "volume", "AAPL.US", "--format", "json"])


if __name__ == "__main__":
    unittest.main()
