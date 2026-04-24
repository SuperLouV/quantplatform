"""Build local preset stock pools for the first dashboard version."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from quant_platform.clients import PRESET_POOLS
from quant_platform.config import Settings
from quant_platform.core.product_models import StockPoolMember, StockPoolSnapshot
from quant_platform.services.bootstrap import bootstrap_local_state


class PresetPoolService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.artifacts = bootstrap_local_state(settings)

    def build_pools(self) -> list[StockPoolSnapshot]:
        pools: list[StockPoolSnapshot] = []
        for config in PRESET_POOLS:
            pools.append(
                StockPoolSnapshot(
                    pool_id=config["pool_id"],
                    name=config["name"],
                    pool_type=config["pool_type"],
                    source=config["source"],
                    market="us_equities",
                    symbols=config["symbols"],
                    members=[
                        StockPoolMember(
                            symbol=symbol,
                            sources=[config["source"]],
                            tags=list(config.get("tags", [])),
                            status="pending_data",
                            reasons=["snapshot_not_fetched"],
                        )
                        for symbol in config["symbols"]
                    ],
                    updated_at=datetime.now(tz=UTC),
                    notes=config.get("notes"),
                )
            )
        return pools

    def write_pools(self, pools: list[StockPoolSnapshot]) -> list[Path]:
        paths: list[Path] = []
        for pool in pools:
            path = self.artifacts.layout.stock_pool_path(pool.pool_type, pool.pool_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = asdict(pool)
            payload["updated_at"] = pool.updated_at.isoformat()
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            paths.append(path)
        return paths
