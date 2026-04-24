"""Helpers for UI APIs: pools, snapshots, history, and search."""

from __future__ import annotations

import json
from pathlib import Path

from quant_platform.config import Settings
from quant_platform.i18n import (
    localize_pool_name,
    localize_snapshot_payload,
    localize_symbol_name,
)
from quant_platform.services.ai_analysis import AIAnalysisService
from quant_platform.services.bootstrap import bootstrap_local_state
from quant_platform.services.stock_snapshot_batch import StockSnapshotBatchService


class UIDataService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.artifacts = bootstrap_local_state(settings)
        self.snapshot_batch = StockSnapshotBatchService(settings)
        self.client = self.snapshot_batch.client
        self.ai_analysis = AIAnalysisService()

    def list_pools(self) -> list[dict[str, object]]:
        pools: list[dict[str, object]] = []
        for path in sorted((self.artifacts.layout.storage.reference_dir / "system" / "stock_pools").glob("*/*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            pools.append(
                {
                    "pool_id": payload["pool_id"],
                    "name": payload["name"],
                    "name_zh": localize_pool_name(payload["pool_id"], payload.get("name")),
                    "pool_type": payload["pool_type"],
                    "source": payload["source"],
                    "symbol_count": len(payload.get("symbols", [])),
                    "path": str(path.relative_to(self.artifacts.layout.storage.reference_dir.parent)),
                }
            )
        return pools

    def load_pool_payload(self, pool_id: str) -> dict[str, object]:
        path = self._find_pool_path(pool_id)
        if path is None:
            raise FileNotFoundError(f"Pool not found: {pool_id}")
        return json.loads(path.read_text(encoding="utf-8"))

    def load_pool_dashboard(self, pool_id: str) -> dict[str, object]:
        pool = self.snapshot_batch.load_pool(self._find_pool_path(pool_id))
        snapshots = [self.load_or_fetch_snapshot(symbol, pool_id=pool.pool_id) for symbol in pool.symbols]
        return {
            "generated_at": self._now_iso(),
            "pool": {
                "pool_id": pool.pool_id,
                "name": pool.name,
                "name_zh": localize_pool_name(pool.pool_id, pool.name),
                "pool_type": pool.pool_type,
                "source": pool.source,
                "symbol_count": len(pool.symbols),
            },
            "snapshots": [localize_snapshot_payload(snapshot) for snapshot in snapshots],
        }

    def load_or_fetch_snapshot(self, symbol: str, *, pool_id: str | None = None) -> dict[str, object]:
        path = self.artifacts.layout.stock_snapshot_path(symbol, "json")
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
            if pool_id and pool_id not in payload.get("pool_ids", []):
                payload["pool_ids"] = list(dict.fromkeys([*payload.get("pool_ids", []), pool_id]))
                path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            return localize_snapshot_payload(payload)

        quote = self.client.fetch_quote_snapshot(symbol)
        snapshot = self.snapshot_batch.create_snapshot_from_quote(symbol, pool_ids=[pool_id] if pool_id else [], quote=quote)
        self.snapshot_batch.write_snapshot(snapshot)
        return localize_snapshot_payload(self.snapshot_batch.serialize_snapshot(snapshot))

    def history(self, symbol: str, period: str = "6mo", interval: str = "1d") -> dict[str, object]:
        return {
            "symbol": symbol,
            "period": period,
            "interval": interval,
            "points": self.client.fetch_chart_history(symbol, period=period, interval=interval),
        }

    def analysis(self, symbol: str, *, pool_id: str | None = None) -> dict[str, object]:
        snapshot_payload = self.load_or_fetch_snapshot(symbol, pool_id=pool_id)
        history = self.client.fetch_chart_history(symbol, period="6mo", interval="1d")
        snapshot = self.snapshot_batch.create_snapshot_from_quote(
            symbol=symbol,
            pool_ids=list(snapshot_payload.get("pool_ids", [])),
            quote=snapshot_payload,
        )
        analysis = self.ai_analysis.create_simple_market_analysis(snapshot, history)
        return {
            "analysis_id": analysis.analysis_id,
            "target_id": analysis.target_id,
            "risk_level": analysis.risk_level,
            "recommendation": analysis.recommendation,
            "summary": analysis.summary,
            "key_points": analysis.key_points,
            "warnings": analysis.warnings,
            "generated_at": analysis.generated_at.isoformat() if analysis.generated_at else None,
        }

    def search(self, query: str, limit: int = 8) -> list[dict[str, object]]:
        results = self.client.search_symbols(query, limit=limit)
        return [
            {
                **item,
                "name_zh": localize_symbol_name(str(item.get("symbol") or ""), item.get("name")),
            }
            for item in results
        ]

    def _find_pool_path(self, pool_id: str) -> Path | None:
        base = self.artifacts.layout.storage.reference_dir / "system" / "stock_pools"
        matches = list(base.glob(f"*/{pool_id}.json"))
        return matches[0] if matches else None

    @staticmethod
    def _now_iso() -> str:
        from datetime import UTC, datetime
        return datetime.now(tz=UTC).isoformat()
