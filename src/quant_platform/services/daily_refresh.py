"""End-of-day refresh pipeline for next-session preparation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from quant_platform.config import Settings
from quant_platform.services.bootstrap import bootstrap_local_state
from quant_platform.services.market_events import MarketEventService
from quant_platform.services.operation_log import OperationLogger, operation_log_root
from quant_platform.services.stock_snapshot_batch import StockSnapshotBatchService
from quant_platform.services.yfinance_history import YFinanceHistoryUpdater
from quant_platform.time_utils import iso_beijing, latest_completed_us_market_date, now_beijing


@dataclass(slots=True)
class DailyRefreshResult:
    pool_id: str
    market_date_us: date
    generated_at_beijing: str
    summary_path: Path
    dashboard_path: Path
    snapshot_count: int
    history: dict[str, dict[str, Any]]
    market_events_count: int | None = None


class DailyRefreshService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.artifacts = bootstrap_local_state(settings)
        self.snapshot_batch = StockSnapshotBatchService(settings)
        self.history_updater = YFinanceHistoryUpdater(settings)
        self.market_events = MarketEventService(settings)
        self.logger = OperationLogger(operation_log_root(settings), "daily_refresh")

    def run(
        self,
        *,
        pool_path: str | Path,
        market_date_us: date | None = None,
        workers: int = 8,
        update_events: bool = True,
    ) -> DailyRefreshResult:
        market_date = market_date_us or latest_completed_us_market_date(now_beijing())
        pool = self.snapshot_batch.load_pool(pool_path)
        self.logger.info(
            "daily_refresh.start",
            pool_id=pool.pool_id,
            symbols=len(pool.symbols),
            market_date_us=market_date.isoformat(),
            workers=workers,
            update_events=update_events,
        )

        history_results: dict[str, dict[str, Any]] = {}
        for symbol in pool.symbols:
            try:
                result = self.history_updater.update_symbol(symbol, end=market_date + timedelta(days=1))
                status = _history_status(result.cursor, market_date)
                history_results[symbol] = {
                    "status": status,
                    "rows_fetched": result.rows_written,
                    "rows_written": result.rows_written,
                    "total_rows": result.total_rows,
                    "earliest_date": result.earliest_date,
                    "latest_date": result.latest_date,
                    "cursor": result.cursor,
                    "start_reason": result.start_reason,
                    "requested_start": result.requested_start,
                    "raw_path": str(result.raw_path),
                    "processed_path": str(result.processed_path),
                }
                if status != "success":
                    history_results[symbol]["reason"] = "cursor_before_market_date"
                    self.logger.error(
                        "daily_refresh.history.empty",
                        pool_id=pool.pool_id,
                        symbol=symbol,
                        rows_written=result.rows_written,
                        cursor=result.cursor,
                        market_date_us=market_date.isoformat(),
                    )
            except Exception as exc:  # noqa: BLE001 - keep the daily refresh moving across symbols.
                history_results[symbol] = {"status": "error", "error": str(exc)}
                self.logger.error("daily_refresh.history.error", pool_id=pool.pool_id, symbol=symbol, error=str(exc))

        snapshot_paths, dashboard_path = self.snapshot_batch.update_pool(pool, max_workers=workers)

        market_events_count: int | None = None
        if update_events:
            try:
                events = self.market_events.update_events()
                market_events_count = len(events.events)
            except Exception as exc:  # noqa: BLE001 - event failures should be visible but not block quote refresh.
                self.logger.error("daily_refresh.market_events.error", pool_id=pool.pool_id, error=str(exc))

        result = DailyRefreshResult(
            pool_id=pool.pool_id,
            market_date_us=market_date,
            generated_at_beijing=iso_beijing(),
            summary_path=self._summary_path(pool.pool_id, market_date),
            dashboard_path=dashboard_path,
            snapshot_count=len(snapshot_paths),
            history=history_results,
            market_events_count=market_events_count,
        )
        self._write_summary(result)
        self.logger.info(
            "daily_refresh.success",
            pool_id=pool.pool_id,
            market_date_us=market_date.isoformat(),
            summary_path=str(result.summary_path),
            dashboard_path=str(dashboard_path),
            snapshot_count=len(snapshot_paths),
            history_success=_count_history_status(history_results, "success"),
            history_empty=_count_history_status(history_results, "empty"),
            history_error=_count_history_status(history_results, "error"),
            market_events_count=market_events_count,
        )
        return result

    def _summary_path(self, pool_id: str, market_date_us: date) -> Path:
        return self.settings.storage.reference_dir / "system" / "daily_refresh" / f"{pool_id}_{market_date_us.isoformat()}.json"

    def _write_summary(self, result: DailyRefreshResult) -> None:
        result.summary_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "generated_at_beijing": result.generated_at_beijing,
            "timezone": "Asia/Shanghai",
            "market_date_us": result.market_date_us.isoformat(),
            "market_timezone": "America/New_York",
            "pool_id": result.pool_id,
            "dashboard_path": str(result.dashboard_path),
            "snapshot_count": result.snapshot_count,
            "market_events_count": result.market_events_count,
            "history": result.history,
        }
        result.summary_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _history_status(cursor: str | None, market_date_us: date) -> str:
    if cursor is None:
        return "empty"
    try:
        return "success" if date.fromisoformat(cursor) >= market_date_us else "empty"
    except ValueError:
        return "empty"


def _count_history_status(history_results: dict[str, dict[str, Any]], status: str) -> int:
    return sum(1 for item in history_results.values() if item.get("status") == status)
