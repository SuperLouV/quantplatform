"""Aggregation helpers for product-facing stock snapshots."""

from __future__ import annotations

from datetime import UTC, datetime

from quant_platform.core.models import Bar, Security, TradingCalendarEvent
from quant_platform.core.product_models import StockSnapshot
from quant_platform.screeners.models import ScreeningDecision, ScreeningSnapshot


class StockSnapshotService:
    def build_snapshot(
        self,
        *,
        symbol: str,
        pool_ids: list[str],
        screening_snapshot: ScreeningSnapshot | None = None,
        screening_decision: ScreeningDecision | None = None,
        security: Security | None = None,
        latest_bar: Bar | None = None,
        events: list[TradingCalendarEvent] | None = None,
        indicators: dict[str, float | str | None] | None = None,
    ) -> StockSnapshot:
        as_of = latest_bar.timestamp if latest_bar else _utcnow()
        return StockSnapshot(
            symbol=symbol,
            pool_ids=pool_ids,
            latest_close=latest_bar.close if latest_bar else screening_snapshot.price if screening_snapshot else None,
            market_cap=(
                security.market_cap
                if security and security.market_cap is not None
                else screening_snapshot.market_cap if screening_snapshot else None
            ),
            avg_dollar_volume=screening_snapshot.avg_dollar_volume if screening_snapshot else None,
            exchange=security.exchange if security and security.exchange else screening_snapshot.exchange if screening_snapshot else None,
            indicators=indicators or {},
            events=[
                {
                    "event_type": event.event_type,
                    "event_date": event.event_date.isoformat(),
                    "provider": event.provider,
                }
                for event in (events or [])
            ],
            screening_status=screening_decision.status if screening_decision else "pending_data",
            screening_reasons=list(screening_decision.reasons) if screening_decision else ["missing_screening_decision"],
            as_of=as_of,
        )


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)
