from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from quant_platform.config import AIConfig, AppConfig, DataConfig, SchedulerConfig, Settings, StorageConfig
from quant_platform.portfolio import AccountPosition, AccountSnapshot
from quant_platform.risk import RiskPolicy
from quant_platform.services.portfolio_health import AccountHealthService


class _FakeAccountService:
    def snapshot(self, *, currency: str = "USD") -> AccountSnapshot:
        return AccountSnapshot(
            provider="longbridge_cli",
            generated_at_beijing="2026-05-05T10:00:00+08:00",
            currency=currency,
            net_assets=20_000,
            available_cash=3_000,
            positions=[
                AccountPosition(symbol="AAPL.US", name="Apple", quantity=20, cost_price=180, market_price=200, market_value=4_000)
            ],
        )


class _FakeEvents:
    def load_events(self, *, start: date | None = None, end: date | None = None):
        return []


class AccountHealthServiceTest(unittest.TestCase):
    def test_generate_writes_account_health_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = _settings(Path(tmp))
            snapshot_path = settings.storage.processed_dir / "snapshots" / "AAPL.json"
            snapshot_path.parent.mkdir(parents=True)
            snapshot_path.write_text(
                json.dumps({"symbol": "AAPL", "sector": "Technology", "indicators": {"atr_14": 5}}),
                encoding="utf-8",
            )
            service = AccountHealthService(
                settings,
                account_service=_FakeAccountService(),  # type: ignore[arg-type]
                risk_policy=RiskPolicy(max_position_weight=0.10),
            )
            service.market_events = _FakeEvents()  # type: ignore[assignment]

            result = service.generate(as_of=date(2026, 5, 5))

            payload = json.loads(result.json_path.read_text(encoding="utf-8"))
            self.assertEqual(result.position_count, 1)
            self.assertEqual(payload["risk_assessment"]["positions"][0]["symbol"], "AAPL")
            self.assertTrue(result.markdown_path.exists())


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
