"""Create and persist a dedicated Nasdaq-100 stock pool."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from quant_platform.clients import NASDAQ_100_SYMBOLS
from quant_platform.config import Settings
from quant_platform.core.product_models import StockPoolMember, StockPoolSnapshot
from quant_platform.services.bootstrap import bootstrap_local_state


class Nasdaq100PoolService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.artifacts = bootstrap_local_state(settings)

    def build_pool(self) -> StockPoolSnapshot:
        members = [
            StockPoolMember(
                symbol=symbol,
                sources=["nasdaq100"],
                tags=["index_constituent", "nasdaq100"],
                status="pending_data",
                reasons=["snapshot_not_fetched"],
            )
            for symbol in NASDAQ_100_SYMBOLS
        ]
        return StockPoolSnapshot(
            pool_id="nasdaq100",
            name="Nasdaq-100",
            pool_type="index",
            source="nasdaq100_constituents_2026-04-24",
            market="us_equities",
            symbols=[member.symbol for member in members],
            members=members,
            updated_at=datetime.now(tz=UTC),
            notes="Constituent list captured from StockAnalysis Nasdaq-100 page on 2026-04-24.",
        )

    def write_pool(self, pool: StockPoolSnapshot) -> Path:
        path = self.artifacts.layout.stock_pool_path(pool.pool_type, pool.pool_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(pool)
        payload["updated_at"] = pool.updated_at.isoformat()
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path
