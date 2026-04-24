"""Product-level stock pool service built on top of screeners."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from quant_platform.config import Settings
from quant_platform.core.product_models import StockPoolMember, StockPoolSnapshot
from quant_platform.screeners import UniverseBuildResult, UniverseBuilder, UniverseConfig
from quant_platform.services.bootstrap import bootstrap_local_state


class StockPoolService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.artifacts = bootstrap_local_state(settings)

    def build_from_config(self, config: UniverseConfig) -> list[StockPoolSnapshot]:
        builder = UniverseBuilder(config)
        result = builder.build()
        return self._to_pool_snapshots(result, config.market)

    def write_snapshots(self, pools: list[StockPoolSnapshot]) -> list[Path]:
        paths: list[Path] = []
        for pool in pools:
            path = self.artifacts.layout.stock_pool_path(pool.pool_type, pool.pool_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(_serialize_dataclass(pool), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            paths.append(path)
        return paths

    def _to_pool_snapshots(
        self,
        result: UniverseBuildResult,
        market: str,
    ) -> list[StockPoolSnapshot]:
        decisions = {item.symbol: item for item in result.decisions}
        updated_at = _utcnow()
        return [
            self._build_pool(
                pool_id="theme_pool",
                name="Theme Pool",
                pool_type="theme",
                source="manual_and_theme",
                market=market,
                candidates=result.theme_pool,
                decisions=decisions,
                updated_at=updated_at,
            ),
            self._build_pool(
                pool_id="system_pool",
                name="System Pool",
                pool_type="system",
                source="system_and_ai",
                market=market,
                candidates=result.system_pool,
                decisions=decisions,
                updated_at=updated_at,
            ),
            self._build_pool(
                pool_id="watchlist",
                name="Watchlist",
                pool_type="watchlist",
                source="merged_candidates",
                market=market,
                candidates=result.watchlist,
                decisions=decisions,
                updated_at=updated_at,
            ),
            self._build_pool(
                pool_id="tradable_universe",
                name="Tradable Universe",
                pool_type="tradable",
                source="screening_passed",
                market=market,
                candidates=result.tradable_universe,
                decisions=decisions,
                updated_at=updated_at,
            ),
        ]

    def _build_pool(
        self,
        *,
        pool_id: str,
        name: str,
        pool_type: str,
        source: str,
        market: str,
        candidates: list[object],
        decisions: dict[str, object],
        updated_at: datetime,
    ) -> StockPoolSnapshot:
        members: list[StockPoolMember] = []
        for candidate in candidates:
            decision = decisions.get(candidate.symbol)
            members.append(
                StockPoolMember(
                    symbol=candidate.symbol,
                    sources=sorted(candidate.sources),
                    themes=sorted(candidate.themes),
                    tags=sorted(candidate.tags),
                    status=decision.status if decision else "candidate",
                    reasons=list(decision.reasons) if decision else [],
                )
            )
        return StockPoolSnapshot(
            pool_id=pool_id,
            name=name,
            pool_type=pool_type,
            source=source,
            market=market,
            symbols=[member.symbol for member in members],
            members=members,
            updated_at=updated_at,
        )


def _serialize_dataclass(value: object) -> dict[str, object]:
    payload = asdict(value)
    updated_at = payload.get("updated_at")
    if isinstance(updated_at, datetime):
        payload["updated_at"] = updated_at.isoformat()
    return payload


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)
