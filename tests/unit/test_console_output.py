from __future__ import annotations

import io
import os
import unittest
from contextlib import redirect_stderr

from quant_platform.console_output import quiet_known_native_stderr


class ConsoleOutputTest(unittest.TestCase):
    def test_quiet_known_native_stderr_filters_arrow_cpu_noise(self) -> None:
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            with quiet_known_native_stderr():
                os.write(2, b"/arrow/util/cpu_info.cc:242: IOError: sysctlbyname failed for 'hw.l1dcachesize'\n")
                os.write(
                    2,
                    b'HTTP Error 404: {"quoteSummary":{"error":{"description":"No fundamentals data found for symbol: QQQ"}}}\n',
                )
                os.write(2, b"real error line\n")

        output = stderr.getvalue()
        self.assertNotIn("cpu_info.cc", output)
        self.assertNotIn("No fundamentals data found", output)
        self.assertIn("real error line", output)


if __name__ == "__main__":
    unittest.main()
