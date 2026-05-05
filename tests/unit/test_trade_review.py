from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from quant_platform.config import AIConfig, AppConfig, DataConfig, SchedulerConfig, Settings, StorageConfig
from quant_platform.services.trade_review import TradeReviewService


class _FakeLongbridgeClient:
    provider_name = "longbridge_cli"

    def fetch_history_orders(self, *, start: date | None = None, end: date | None = None):
        return [{"symbol": "AAPL.US"}]

    def fetch_history_executions(self, *, start: date | None = None, end: date | None = None):
        return [
            {"symbol": "AAPL.US", "side": "BUY", "quantity": "10", "price": "100", "executed_at": "2026-01-02T15:00:00+00:00"},
            {"symbol": "AAPL.US", "side": "SELL", "quantity": "10", "price": "110", "executed_at": "2026-01-10T15:00:00+00:00"},
            {"symbol": "MSFT.US", "side": "BUY", "quantity": "5", "price": "200", "executed_at": "2026-02-01T15:00:00+00:00"},
            {"symbol": "MSFT.US", "side": "SELL", "quantity": "5", "price": "190", "executed_at": "2026-02-05T15:00:00+00:00"},
        ]


class TradeReviewServiceTest(unittest.TestCase):
    def test_generate_trade_review_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = TradeReviewService(_settings(Path(tmp)), client=_FakeLongbridgeClient()).generate()  # type: ignore[arg-type]

            payload = json.loads(result.json_path.read_text(encoding="utf-8"))
            self.assertEqual(result.closed_trade_count, 2)
            self.assertEqual(payload["summary"]["win_rate_pct"], 50.0)
            self.assertEqual(payload["by_symbol"]["AAPL"]["total_realized_pnl"], 100.0)
            self.assertEqual(payload["by_month"]["2026-02"]["total_realized_pnl"], -50.0)


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


if __name__ == "__main__":
    unittest.main()
