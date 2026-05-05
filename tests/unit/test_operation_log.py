from __future__ import annotations

import io
import json
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from quant_platform.services.operation_log import OperationLogger


class OperationLoggerTest(unittest.TestCase):
    def test_console_logging_is_controlled_by_env(self) -> None:
        with TemporaryDirectory() as temp_dir:
            stderr = io.StringIO()
            with patch.dict("os.environ", {"QP_LOG_TO_CONSOLE": "1"}, clear=False), redirect_stderr(stderr):
                OperationLogger(Path(temp_dir), "test").info("demo.action", symbol="AAPL")

            output = stderr.getvalue()
            self.assertIn("INFO test.demo.action", output)
            self.assertIn("symbol=AAPL", output)

    def test_jsonl_log_is_always_written(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            OperationLogger(root, "test").error("demo.error", api_key="secret")

            logs = list(root.glob("test_*.jsonl"))
            self.assertEqual(len(logs), 1)
            payload = json.loads(logs[0].read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(payload["level"], "error")
            self.assertEqual(payload["api_key"], "***")

    def test_notice_prints_important_line_to_stdout(self) -> None:
        with TemporaryDirectory() as temp_dir:
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                OperationLogger(Path(temp_dir), "daily_refresh").notice("daily_refresh.success", pool_id="core")

            output = stdout.getvalue()
            self.assertIn("INFO daily_refresh.success", output)
            self.assertNotIn("daily_refresh.daily_refresh.success", output)
            self.assertIn("pool_id=core", output)


if __name__ == "__main__":
    unittest.main()
