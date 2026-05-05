from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace

from quant_platform.config import AIConfig, AppConfig, DataConfig, SchedulerConfig, Settings, StorageConfig
from quant_platform.portfolio import AccountPosition, AccountSnapshot
from quant_platform.services.auto_scanner import AutoScannerService


class _FakeUIData:
    def scanner(self, pool_id: str):
        return {
            "summary": {"candidate_buy": 1, "watch": 0, "risk_avoid": 0, "insufficient_data": 0},
            "candidates": [
                {"symbol": "MSFT", "price": 100, "score": 80, "action": "候选买入", "risk_level": "低", "momentum_rank_pct": 90}
            ],
        }


class _FakeAccount:
    def snapshot(self, *, currency: str = "USD") -> AccountSnapshot:
        return AccountSnapshot(
            provider="longbridge_cli",
            generated_at_beijing="2026-05-05T10:00:00+08:00",
            currency=currency,
            net_assets=50_000,
            available_cash=30_000,
            positions=[AccountPosition(symbol="AAPL.US", quantity=100, available_quantity=100, cost_price=90, market_price=100)],
        )


class _FakeOptionsAdvice:
    def __init__(self, root: Path) -> None:
        self.root = root

    def generate(self, **kwargs):
        path = self.root / "options.json"
        path.write_text(
            json.dumps(
                {
                    "positions": [
                        {
                            "symbol": "AAPL",
                            "suggestions": [
                                {
                                    "strategy": "covered_call",
                                    "decision": "继续观察",
                                    "strike": 110,
                                    "expiration": "2026-06-19",
                                    "annualized_return_pct": 12,
                                }
                            ],
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        return SimpleNamespace(json_path=path, markdown_path=self.root / "options.md")


class AutoScannerServiceTest(unittest.TestCase):
    def test_run_combines_stock_and_options_scans(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service = AutoScannerService(
                _settings(root),
                ui_data=_FakeUIData(),  # type: ignore[arg-type]
                account_service=_FakeAccount(),  # type: ignore[arg-type]
                options_advice=_FakeOptionsAdvice(root),  # type: ignore[arg-type]
            )

            result = service.run(pool_id="test", as_of=date(2026, 5, 5))

            payload = json.loads(result.json_path.read_text(encoding="utf-8"))
            self.assertEqual(result.stock_candidate_count, 1)
            self.assertEqual(result.covered_call_count, 1)
            self.assertEqual(result.cash_secured_put_count, 1)
            self.assertEqual(payload["options_scan"]["cash_secured_put_watchlist"][0]["symbol"], "MSFT")


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
