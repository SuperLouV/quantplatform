from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from quant_platform.config import AIConfig, AppConfig, DataConfig, SchedulerConfig, Settings, StorageConfig
from quant_platform.services.ai_analysis import AutomatedAIAnalysisService


class AutomatedAIAnalysisServiceTest(unittest.TestCase):
    def test_analyze_dashboard_writes_json_and_markdown_without_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = _settings(root)
            dashboard = settings.storage.reference_dir / "system" / "dashboard_data.json"
            dashboard.parent.mkdir(parents=True)
            dashboard.write_text(
                json.dumps(
                    {
                        "snapshots": [
                            {
                                "symbol": "AAPL",
                                "pool_ids": ["longbridge_core"],
                                "current_price": 280,
                                "latest_close": 279,
                                "quote_provider_status": "success",
                                "screening_status": "ready",
                                "indicators": {
                                    "sma_20": 260,
                                    "sma_50": 250,
                                    "rsi_14": 58,
                                    "macd_histogram": 1.2,
                                    "atr_14": 5,
                                    "volume_ratio_20": 1.1,
                                },
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            result = AutomatedAIAnalysisService(settings).analyze_dashboard(use_model=False)

            self.assertEqual(result.snapshot_count, 1)
            self.assertEqual(result.model_status, "skipped")
            self.assertTrue(result.json_path.exists())
            self.assertTrue(result.markdown_path.exists())
            payload = json.loads(result.json_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["analyses"][0]["result"]["target_id"], "AAPL")
            self.assertEqual(payload["analyses"][0]["structured_report"]["technical_interpretation"]["state"], "偏强")

    def test_analyze_latest_account_health_calls_model_and_writes_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = _settings_with_model(root)
            report_dir = root / "data" / "reports" / "account_health"
            report_dir.mkdir(parents=True)
            (report_dir / "account_health_20260505T000000Z.json").write_text(
                json.dumps(
                    {
                        "analysis_id": "account_health:test",
                        "generated_at_beijing": "2026-05-05T08:00:00+08:00",
                        "as_of": "2026-05-05",
                        "data_sources": {"account": "longbridge_cli"},
                        "account": {
                            "currency": "USD",
                            "net_assets": 20000,
                            "available_cash": 500,
                            "risk_level": "Safe",
                            "position_count": 2,
                        },
                        "risk_assessment": {
                            "equity": 20000,
                            "cash": 500,
                            "cash_ratio_pct": 2.5,
                            "position_count": 2,
                            "health_score": 45,
                            "health_state": "观察",
                            "positions": [{"symbol": "AAPL", "weight_pct": 12.0, "market_value": 2400}],
                            "recommendations": ["AAPL 权重偏高，暂停加仓。"],
                            "warnings": ["现金比例偏低。"],
                        },
                        "position_actions": [{"symbol": "AAPL", "action": "暂停加仓。"}],
                    }
                ),
                encoding="utf-8",
            )

            result = AutomatedAIAnalysisService(settings, client=_FakeChatClient()).analyze_latest_account_health()

            self.assertEqual(result.model_status, "success")
            self.assertEqual(result.scenario, "account_health")
            markdown = result.markdown_path.read_text(encoding="utf-8")
            self.assertIn("模型生成的保守解读", markdown)
            self.assertIn("账户健康度", markdown)

    def test_analyze_latest_options_advice_calls_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = _settings_with_model(root)
            report_dir = root / "data" / "reports" / "options_advice"
            report_dir.mkdir(parents=True)
            (report_dir / "options_advice_20260505T000000Z.json").write_text(
                json.dumps(
                    {
                        "analysis_id": "options_advice:test",
                        "generated_at_beijing": "2026-05-05T08:00:00+08:00",
                        "as_of": "2026-05-05",
                        "account_summary": {"equity_for_risk": 20000, "cash_for_cash_secured_put": 500},
                        "summary": {"suggestion_count": 1, "decision_counts": {"不适合": 1}},
                        "positions": [
                            {
                                "symbol": "AAPL",
                                "quantity": 4,
                                "underlying_price": 280,
                                "suggestions": [
                                    {
                                        "strategy": "covered_call",
                                        "decision": "不适合",
                                        "reason": "Covered call 需要至少 100 股可用正股。",
                                    }
                                ],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = AutomatedAIAnalysisService(settings, client=_FakeChatClient()).analyze_latest_options_advice()

            self.assertEqual(result.model_status, "success")
            self.assertEqual(result.scenario, "options_advice")
            payload = json.loads(result.json_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["prompt_payload"]["scenario"], "options_advice")

    def test_analyze_stock_technical_uses_snapshot_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = _settings_with_model(root)
            snapshot_dir = settings.storage.processed_dir / "snapshots"
            snapshot_dir.mkdir(parents=True)
            (snapshot_dir / "AAPL.json").write_text(
                json.dumps(
                    {
                        "symbol": "AAPL",
                        "pool_ids": ["longbridge_core"],
                        "current_price": 280,
                        "latest_close": 279,
                        "latest_history_date_us": "2026-05-04",
                        "quote_provider_status": "success",
                        "screening_status": "ready",
                        "indicators": {
                            "sma_20": 260,
                            "sma_50": 250,
                            "rsi_14": 58,
                            "macd_histogram": 1.2,
                            "atr_14": 5,
                        },
                    }
                ),
                encoding="utf-8",
            )

            result = AutomatedAIAnalysisService(settings, client=_FakeChatClient()).analyze_stock_technical("AAPL")

            self.assertEqual(result.model_status, "success")
            self.assertEqual(result.target_id, "AAPL")
            payload = json.loads(result.json_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["prompt_payload"]["structured_context"]["symbol"], "AAPL")


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
        ai=AIConfig(provider="none"),
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
        return {"choices": [{"message": {"content": "## 一句话结论\n\n模型生成的保守解读。"}}]}


if __name__ == "__main__":
    unittest.main()
