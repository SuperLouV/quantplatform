from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from quant_platform.config import AIConfig, AppConfig, DataConfig, SchedulerConfig, Settings, StorageConfig
from quant_platform.services.decision_chat import DecisionChatService


class DecisionChatServiceTest(unittest.TestCase):
    def test_ask_uses_local_artifacts_and_calls_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = _settings_with_model(root)
            reports = root / "data" / "reports"
            (reports / "account_health").mkdir(parents=True)
            (reports / "options_advice").mkdir(parents=True)
            (reports / "macro_risk").mkdir(parents=True)
            (reports / "ai_analysis").mkdir(parents=True)
            (settings.storage.reference_dir / "system" / "scan_results").mkdir(parents=True)
            (settings.storage.processed_dir / "snapshots").mkdir(parents=True)

            (reports / "daily_2026-05-05.md").write_text("# 每日报告\n\nAAPL 需要复核。\n", encoding="utf-8")
            (reports / "account_health" / "account_health_20260505T000000Z.json").write_text(
                json.dumps({"risk_assessment": {"health_state": "观察", "positions": [{"symbol": "AAPL"}]}}),
                encoding="utf-8",
            )
            (reports / "options_advice" / "options_advice_20260505T000000Z.json").write_text(
                json.dumps({"positions": [{"symbol": "AAPL", "suggestions": []}]}),
                encoding="utf-8",
            )
            (reports / "macro_risk" / "macro_risk_20260505T000000Z.json").write_text(
                json.dumps({"risk_state": "neutral", "sentiment_state": "risk_on"}),
                encoding="utf-8",
            )
            (reports / "ai_analysis" / "ai_account_health_latest.md").write_text("## 一句话结论\n\n保守复核。\n", encoding="utf-8")
            (settings.storage.reference_dir / "system" / "scan_results" / "longbridge_core_2026-05-05.json").write_text(
                json.dumps({"candidates": [{"symbol": "AAPL", "score": 70}], "summary": {"candidate_count": 1}}),
                encoding="utf-8",
            )
            (settings.storage.processed_dir / "snapshots" / "AAPL.json").write_text(
                json.dumps({"symbol": "AAPL", "current_price": 200}),
                encoding="utf-8",
            )

            client = _FakeChatClient()
            result = DecisionChatService(settings, client=client).ask("我应该先看 AAPL 的什么风险？", symbol="AAPL")

            self.assertEqual(result.model_status, "success")
            self.assertIn("人工复核", result.answer_markdown)
            self.assertGreaterEqual(len(result.source_paths), 6)
            prompt = client.messages[-1]["content"]
            self.assertIn("AAPL", prompt)
            self.assertIn("manual_review_only_no_auto_order", prompt)

    def test_ask_returns_error_when_provider_missing_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = _settings(root)
            result = DecisionChatService(settings).ask("现在账户风险如何？")

            self.assertEqual(result.model_status, "error")
            self.assertEqual(result.answer_markdown, "")
            self.assertTrue(any("API key" in warning for warning in result.warnings))


def _settings(root: Path) -> Settings:
    return Settings(
        app=AppConfig(name="test", env="test"),
        data=DataConfig(provider="yfinance", timezone="America/New_York"),
        storage=StorageConfig(
            raw_dir=root / "data" / "raw",
            processed_dir=root / "data" / "processed",
            reference_dir=root / "data" / "reference",
            cache_dir=root / "data" / "cache",
            state_db=root / "data" / "system" / "state.db",
        ),
        scheduler=SchedulerConfig(),
        ai=AIConfig(provider="deepseek", api_key="", base_url="https://api.deepseek.com", model="deepseek-v4-flash"),
    )


def _settings_with_model(root: Path) -> Settings:
    settings = _settings(root)
    settings.ai.provider = "local_openai"
    settings.ai.base_url = "http://127.0.0.1:1/v1"
    settings.ai.model = "fake-model"
    return settings


class _FakeChatClient:
    def chat(self, messages: list[dict[str, str]], *, temperature: float, max_tokens: int) -> dict[str, object]:
        self.messages = messages
        self.temperature = temperature
        self.max_tokens = max_tokens
        return {"choices": [{"message": {"content": "## 一句话结论\n\n需要人工复核仓位、止损和期权风险。"}}]}


if __name__ == "__main__":
    unittest.main()
