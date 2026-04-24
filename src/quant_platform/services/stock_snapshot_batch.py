"""Batch snapshot update service for stock pools."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from quant_platform.clients.yfinance import YFinanceClient
from quant_platform.config import Settings
from quant_platform.core.product_models import StockPoolSnapshot, StockSnapshot
from quant_platform.services.ai_analysis import AIAnalysisService
from quant_platform.services.bootstrap import bootstrap_local_state
from quant_platform.services.stock_snapshot import StockSnapshotService


class StockSnapshotBatchService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.artifacts = bootstrap_local_state(settings)
        self.client = YFinanceClient()
        self.snapshot_service = StockSnapshotService()
        self.ai_service = AIAnalysisService()

    def load_pool(self, path: str | Path) -> StockPoolSnapshot:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        members = payload.get("members", [])
        return StockPoolSnapshot(
            pool_id=payload["pool_id"],
            name=payload["name"],
            pool_type=payload["pool_type"],
            source=payload["source"],
            market=payload["market"],
            symbols=payload["symbols"],
            members=[],
            updated_at=datetime.fromisoformat(payload["updated_at"]),
            notes=payload.get("notes"),
        )

    def update_pool(self, pool: StockPoolSnapshot, *, max_workers: int = 8) -> tuple[list[Path], Path]:
        snapshot_paths: list[Path] = []
        dashboard_entries: list[dict[str, object]] = []

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(self.client.fetch_quote_snapshot, symbol): symbol
                for symbol in pool.symbols
            }
            for future in as_completed(futures):
                symbol = futures[future]
                try:
                    quote = future.result()
                    snapshot = self.create_snapshot_from_quote(symbol, pool_ids=[pool.pool_id], quote=quote)
                except Exception as exc:
                    snapshot = StockSnapshot(
                        symbol=symbol,
                        pool_ids=[pool.pool_id],
                        screening_status="error",
                        screening_reasons=[str(exc)],
                        as_of=datetime.now(tz=UTC),
                    )

                path = self.write_snapshot(snapshot)
                snapshot_paths.append(path)
                dashboard_entries.append(self.serialize_snapshot(snapshot))

        dashboard_path = self.write_dashboard(pool, dashboard_entries)
        return snapshot_paths, dashboard_path

    def write_snapshot(self, snapshot: StockSnapshot) -> Path:
        path = self.artifacts.layout.stock_snapshot_path(snapshot.symbol, "json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(_serialize_snapshot(snapshot), ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def write_dashboard(self, pool: StockPoolSnapshot, snapshots: list[dict[str, object]]) -> Path:
        path = self.artifacts.layout.reference_file_path("system", "dashboard_data", "json")
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "generated_at": datetime.now(tz=UTC).isoformat(),
            "pool": {
                "pool_id": pool.pool_id,
                "name": pool.name,
                "pool_type": pool.pool_type,
                "source": pool.source,
                "symbol_count": len(pool.symbols),
            },
            "snapshots": snapshots,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def create_snapshot_from_quote(
        self,
        symbol: str,
        *,
        pool_ids: list[str],
        quote: dict[str, object],
    ) -> StockSnapshot:
        return StockSnapshot(
            symbol=symbol,
            pool_ids=pool_ids,
            company_name=quote.get("company_name"),
            sector=quote.get("sector"),
            industry=quote.get("industry"),
            currency=quote.get("currency"),
            open_price=quote.get("open_price"),
            high_price=quote.get("high_price"),
            low_price=quote.get("low_price"),
            latest_close=quote.get("latest_close"),
            previous_close=quote.get("previous_close"),
            change_percent=quote.get("change_percent"),
            latest_volume=quote.get("latest_volume"),
            market_cap=quote.get("market_cap"),
            avg_dollar_volume=quote.get("avg_dollar_volume"),
            trailing_pe=quote.get("trailing_pe"),
            forward_pe=quote.get("forward_pe"),
            next_earnings_date=quote.get("next_earnings_date"),
            exchange=quote.get("exchange"),
            screening_status="ready",
            screening_reasons=[],
            as_of=datetime.now(tz=UTC),
        )

    def serialize_snapshot(self, snapshot: StockSnapshot) -> dict[str, object]:
        return _serialize_snapshot(snapshot)


def _serialize_snapshot(snapshot: StockSnapshot) -> dict[str, object]:
    payload = asdict(snapshot)
    if snapshot.as_of is not None:
        payload["as_of"] = snapshot.as_of.isoformat()
    return payload
