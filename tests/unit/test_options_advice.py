from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from quant_platform.config import AIConfig, AppConfig, DataConfig, SchedulerConfig, Settings, StorageConfig
from quant_platform.options.advice import AccountOptionsAdviceService
from quant_platform.portfolio import AccountPosition, AccountSnapshot


class _FakeAccountService:
    def snapshot(self, *, currency: str = "USD") -> AccountSnapshot:
        return AccountSnapshot(
            provider="longbridge_cli",
            generated_at_beijing="2026-05-05T10:00:00+08:00",
            currency=currency,
            net_assets=100_000,
            total_cash=50_000,
            available_cash=50_000,
            positions=[
                AccountPosition(
                    symbol="AAPL.US",
                    name="Apple",
                    market="US",
                    quantity=100,
                    available_quantity=100,
                    cost_price=250,
                    market_price=280,
                ),
                AccountPosition(symbol="VOO.US", name="Vanguard S&P 500 ETF", market="US", quantity=10, available_quantity=10, market_price=500),
            ],
        )


class _FakeYFinanceClient:
    def fetch_quote_snapshot(self, symbol: str) -> dict[str, object]:
        return {"symbol": symbol, "current_price": 280, "regular_market_price": 280}

    def fetch_option_expirations(self, symbol: str) -> list[date]:
        return [date(2026, 6, 19)]

    def fetch_option_chain(self, symbol: str, expiration: date) -> dict[str, list[dict[str, object]]]:
        return {
            "calls": [
                {
                    "contract_symbol": "AAPL260619C300",
                    "strike": 300,
                    "bid": 2.0,
                    "ask": 2.2,
                    "open_interest": 1000,
                }
            ],
            "puts": [
                {
                    "contract_symbol": "AAPL260619P250",
                    "strike": 250,
                    "bid": 1.8,
                    "ask": 2.0,
                    "open_interest": 1000,
                }
            ],
        }


class OptionsAdviceTest(unittest.TestCase):
    def test_generate_account_options_advice(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = AccountOptionsAdviceService(
                _settings(Path(tmp)),
                account_service=_FakeAccountService(),  # type: ignore[arg-type]
                yfinance_client=_FakeYFinanceClient(),  # type: ignore[arg-type]
            )

            result = service.generate(as_of=date(2026, 5, 20))

            self.assertEqual(result.position_count, 2)
            self.assertEqual(result.advice_count, 2)
            payload = json.loads(result.json_path.read_text(encoding="utf-8"))
            by_symbol = {item["symbol"]: item for item in payload["positions"]}
            suggestions = by_symbol["AAPL"]["suggestions"]
            self.assertEqual(suggestions[0]["strategy"], "covered_call")
            self.assertIsNotNone(suggestions[0]["annualized_return_pct"])
            self.assertEqual(suggestions[1]["strategy"], "cash_secured_put")
            self.assertEqual(by_symbol["VOO"]["scan_status"], "skipped")


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
