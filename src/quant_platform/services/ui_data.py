"""Helpers for UI APIs: pools, snapshots, history, and search."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd

from quant_platform.config import Settings
from quant_platform.indicators import IndicatorEngine
from quant_platform.i18n import (
    localize_pool_name,
    localize_snapshot_payload,
    localize_symbol_name,
)
from quant_platform.services.ai_analysis import AIAnalysisService
from quant_platform.services.bootstrap import bootstrap_local_state
from quant_platform.services.market_events import MarketEventService
from quant_platform.services.stock_snapshot_batch import StockSnapshotBatchService


class UIDataService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.artifacts = bootstrap_local_state(settings)
        self.snapshot_batch = StockSnapshotBatchService(settings)
        self.client = self.snapshot_batch.client
        self.ai_analysis = AIAnalysisService()
        self.indicator_engine = IndicatorEngine()
        self.market_events = MarketEventService(settings)

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
            self._attach_chart_history_indicators_if_missing(symbol, payload)
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            return localize_snapshot_payload(payload)

        quote = self.client.fetch_quote_snapshot(symbol)
        snapshot = self.snapshot_batch.create_snapshot_from_quote(symbol, pool_ids=[pool_id] if pool_id else [], quote=quote)
        self.snapshot_batch.attach_local_indicators(snapshot)
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

    def market_event_calendar(self, *, start: date | None = None, end: date | None = None) -> dict[str, object]:
        from datetime import UTC, datetime

        return {
            "generated_at": datetime.now(tz=UTC).isoformat(),
            "events": self.market_events.load_events(start=start, end=end),
        }

    def _find_pool_path(self, pool_id: str) -> Path | None:
        base = self.artifacts.layout.storage.reference_dir / "system" / "stock_pools"
        matches = list(base.glob(f"*/{pool_id}.json"))
        return matches[0] if matches else None

    def _attach_chart_history_indicators_if_missing(self, symbol: str, payload: dict[str, object]) -> None:
        indicators = payload.get("indicators")
        if isinstance(indicators, dict) and any(value is not None for value in indicators.values()):
            return

        try:
            history = self.client.fetch_chart_history(symbol, period="1y", interval="1d")
            if len(history) < 20:
                _append_screening_reason(payload, "warning:insufficient_history:图表历史不足 20 根，未生成交易指标。")
                return

            computation = self.indicator_engine.compute(pd.DataFrame(history))
            latest_timestamp = pd.Timestamp(computation.series.iloc[-1]["timestamp"])
            if latest_timestamp.tzinfo is None:
                latest_timestamp = latest_timestamp.tz_localize("UTC")
            else:
                latest_timestamp = latest_timestamp.tz_convert("UTC")
            payload["indicators"] = {
                **computation.latest,
                "indicators_as_of": latest_timestamp.isoformat(),
                "indicators_provider": f"{self.client.provider_name}_chart_history",
            }
        except Exception as exc:  # noqa: BLE001 - UI should degrade instead of breaking on indicator enrichment.
            _append_screening_reason(payload, f"warning:indicator_history_error:图表历史指标生成失败：{exc}")

    @staticmethod
    def _now_iso() -> str:
        from datetime import UTC, datetime
        return datetime.now(tz=UTC).isoformat()


def _append_screening_reason(payload: dict[str, object], reason: str) -> None:
    reasons = payload.get("screening_reasons")
    if not isinstance(reasons, list):
        reasons = []
    if reason not in reasons:
        reasons.append(reason)
    payload["screening_reasons"] = reasons
