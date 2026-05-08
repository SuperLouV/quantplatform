from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from quant_platform.services.ui_data import (
    _ai_insight_from_file,
    _ai_summary_from_file,
    _latest_ai_summary_file,
    _macro_risk_from_market_overview,
)


class UIDashboardHelpersTest(unittest.TestCase):
    def test_ai_summary_prefers_matching_account_pattern_over_newer_options(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            option_path = base / "ai_options_advice_latest.json"
            account_path = base / "ai_account_health_latest.json"
            option_path.write_text(
                json.dumps({"model": {"markdown": "## 一句话结论\n\n期权策略不适合。"}}),
                encoding="utf-8",
            )
            account_path.write_text(
                json.dumps(
                    {
                        "generated_at_beijing": "2026-05-07T06:30:00+08:00",
                        "model": {
                            "markdown": (
                                "好的，以下不构成交易指令。\n\n"
                                "### 一句话结论\n\n"
                                "当前账户现金比例偏低，持仓集中度需要人工复核。\n\n"
                                "### 关键风险\n\n"
                                "- VOO 单股权重超限。\n"
                                "- PDT watch 需要避免高频日内交易。\n"
                            )
                        },
                    }
                ),
                encoding="utf-8",
            )

            latest_account = _latest_ai_summary_file(base, "ai_account_health_*.json")
            insight = _ai_insight_from_file(latest_account, title="持仓账户", source="account_health")

            self.assertEqual(latest_account, account_path)
            self.assertIn("现金比例偏低", _ai_summary_from_file(latest_account) or "")
            self.assertIsNotNone(insight)
            self.assertEqual(insight["title"], "持仓账户")
            self.assertTrue(any("VOO" in line for line in insight["details"]))

    def test_macro_risk_falls_back_to_market_overview(self) -> None:
        payload = _macro_risk_from_market_overview(
            {
                "regime": "中性",
                "spy": {"symbol": "SPY", "price": 733.83, "as_of": "2026-05-06", "state": "偏多"},
                "qqq": {"symbol": "QQQ", "price": 695.77, "as_of": "2026-05-06", "state": "偏多"},
                "vix": {"symbol": "^VIX", "price": 18.71, "as_of": "2026-05-06", "state": "偏紧张"},
            }
        )

        self.assertIsNotNone(payload)
        self.assertEqual(payload["risk_state"], "中性观察")
        self.assertEqual(payload["sentiment_state"], "本地市场快照")
        self.assertEqual(payload["market_date_us"], "2026-05-06")
        self.assertIn("SPY/QQQ/VIX", payload["warnings"][0])


if __name__ == "__main__":
    unittest.main()
