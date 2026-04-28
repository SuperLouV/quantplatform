"""Incremental yfinance history update service."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

from quant_platform.clients.yfinance import YFinanceClient
from quant_platform.config import Settings
from quant_platform.core.models import Bar, DataRequest
from quant_platform.services.bootstrap import bootstrap_local_state
from quant_platform.services.operation_log import OperationLogger, operation_log_root
from quant_platform.storage import DataLayout, SQLiteStateStore, UpdateRunRecord
from quant_platform.time_utils import now_beijing


@dataclass(slots=True)
class YFinanceHistoryUpdateResult:
    symbol: str
    rows_written: int
    raw_path: Path
    processed_path: Path
    cursor: str | None
    start_reason: str
    requested_start: str | None
    earliest_date: str | None
    latest_date: str | None
    total_rows: int


class YFinanceHistoryUpdater:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        artifacts = bootstrap_local_state(settings)
        self.layout: DataLayout = artifacts.layout
        self.state_store: SQLiteStateStore = artifacts.state_store
        self.client = YFinanceClient.from_data_config(settings.data)
        self.logger = OperationLogger(operation_log_root(settings), "yfinance_history")

    def update_symbol(
        self,
        symbol: str,
        *,
        start: date | None = None,
        end: date | None = None,
        interval: str = "1d",
        adjusted: bool = True,
        full_history: bool = False,
    ) -> YFinanceHistoryUpdateResult:
        dataset = "bars"
        run_started = _now_beijing()
        checkpoint = self.state_store.get_checkpoint(self.client.provider_name, dataset, symbol)
        previous_cursor = checkpoint.cursor if checkpoint else None
        effective_start, start_reason = self._resolve_start(
            symbol=symbol,
            explicit_start=start,
            previous_cursor=previous_cursor,
            end=end,
            interval=interval,
            full_history=full_history,
        )
        request = DataRequest(symbol=symbol, start=effective_start, end=end, interval=interval, adjusted=adjusted)
        self.logger.info(
            "yfinance_history.update.start",
            symbol=symbol,
            start=effective_start,
            start_reason=start_reason,
            end=end,
            interval=interval,
            adjusted=adjusted,
            previous_cursor=previous_cursor,
            full_history=full_history,
        )

        self.state_store.mark_attempt(
            self.client.provider_name,
            dataset,
            symbol,
            cursor=previous_cursor,
            note=f"start={effective_start.isoformat() if effective_start else 'full'} reason={start_reason} interval={interval}",
        )

        try:
            bars = self.client.fetch_bars(request)
            raw_path = self._write_raw(symbol, request, bars)
            processed_path = self._write_processed(symbol, bars)
            coverage = _processed_coverage(processed_path)
            cursor = bars[-1].timestamp.date().isoformat() if bars else previous_cursor

            self.state_store.mark_success(
                self.client.provider_name,
                dataset,
                symbol,
                cursor=cursor,
                note=f"rows={len(bars)} total_rows={coverage['total_rows']}",
            )
            self.state_store.record_run(
                UpdateRunRecord(
                    provider=self.client.provider_name,
                    dataset=dataset,
                    symbol=symbol,
                    started_at=run_started,
                    finished_at=_now_beijing(),
                    status="success",
                    rows_written=len(bars),
                    note=f"raw={raw_path.name} processed={processed_path.name}",
                )
            )
            self.logger.info(
                "yfinance_history.update.success",
                symbol=symbol,
                rows_fetched=len(bars),
                total_rows=coverage["total_rows"],
                earliest_date=coverage["earliest_date"],
                latest_date=coverage["latest_date"],
                raw_path=str(raw_path),
                processed_path=str(processed_path),
                cursor=cursor,
                start_reason=start_reason,
                requested_start=effective_start.isoformat() if effective_start else None,
            )
            return YFinanceHistoryUpdateResult(
                symbol=symbol,
                rows_written=len(bars),
                raw_path=raw_path,
                processed_path=processed_path,
                cursor=cursor,
                start_reason=start_reason,
                requested_start=effective_start.isoformat() if effective_start else None,
                earliest_date=coverage["earliest_date"],
                latest_date=coverage["latest_date"],
                total_rows=int(coverage["total_rows"]),
            )
        except Exception as exc:
            self.state_store.mark_failure(
                self.client.provider_name,
                dataset,
                symbol,
                cursor=previous_cursor,
                note=str(exc),
            )
            self.state_store.record_run(
                UpdateRunRecord(
                    provider=self.client.provider_name,
                    dataset=dataset,
                    symbol=symbol,
                    started_at=run_started,
                    finished_at=_now_beijing(),
                    status="failed",
                    rows_written=0,
                    note=str(exc),
                )
            )
            self.logger.error(
                "yfinance_history.update.error",
                symbol=symbol,
                start=effective_start,
                end=end,
                interval=interval,
                adjusted=adjusted,
                start_reason=start_reason,
                full_history=full_history,
                error=str(exc),
            )
            raise

    def _resolve_start(
        self,
        *,
        symbol: str,
        explicit_start: date | None,
        previous_cursor: str | None,
        end: date | None,
        interval: str,
        full_history: bool = False,
    ) -> tuple[date | None, str]:
        if full_history:
            return _full_history_start(), "full_history"

        if explicit_start:
            return explicit_start, "explicit"

        incremental_start = _derive_incremental_start(previous_cursor)
        if interval != "1d":
            return incremental_start, "incremental" if incremental_start else "provider_default"

        lookback_start = _derive_initial_history_start(end, self.settings.data.yfinance_initial_history_years)
        if not previous_cursor:
            return lookback_start, "initial_backfill"

        if self._needs_history_backfill(symbol, lookback_start):
            return lookback_start, "repair_short_history"

        return incremental_start, "incremental"

    def _needs_history_backfill(self, symbol: str, lookback_start: date) -> bool:
        path = self.layout.processed_symbol_path(self.client.provider_name, "bars", symbol)
        if not path.exists():
            self.logger.info(
                "yfinance_history.backfill.required",
                symbol=symbol,
                reason="missing_processed_bars",
                lookback_start=lookback_start.isoformat(),
                path=str(path),
            )
            return True

        try:
            frame = pd.read_parquet(path, columns=["timestamp"])
        except Exception as exc:  # noqa: BLE001 - corrupted local bars should be recoverable by a backfill.
            self.logger.error(
                "yfinance_history.backfill.required",
                symbol=symbol,
                reason="read_processed_bars_failed",
                lookback_start=lookback_start.isoformat(),
                path=str(path),
                error=str(exc),
            )
            return True

        if frame.empty or "timestamp" not in frame:
            self.logger.info(
                "yfinance_history.backfill.required",
                symbol=symbol,
                reason="empty_processed_bars",
                lookback_start=lookback_start.isoformat(),
                path=str(path),
            )
            return True

        earliest = pd.to_datetime(frame["timestamp"], utc=True).min().date()
        if earliest > lookback_start:
            self.logger.info(
                "yfinance_history.backfill.required",
                symbol=symbol,
                reason="history_window_too_short",
                earliest=earliest.isoformat(),
                lookback_start=lookback_start.isoformat(),
                path=str(path),
            )
            return True

        return False

    def _write_raw(self, symbol: str, request: DataRequest, bars: list[Bar]) -> Path:
        partition = _now_beijing().strftime("%Y%m%dT%H%M%S%z")
        path = self.layout.raw_symbol_path(self.client.provider_name, "bars", symbol, partition)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "provider": self.client.provider_name,
            "dataset": "bars",
            "symbol": symbol,
            "request": {
                "start": request.start.isoformat() if request.start else None,
                "end": request.end.isoformat() if request.end else None,
                "interval": request.interval,
                "adjusted": request.adjusted,
            },
            "fetched_at": _now_beijing().isoformat(),
            "records": [
                {
                    "symbol": bar.symbol,
                    "timestamp": bar.timestamp.isoformat(),
                    "open": bar.open,
                    "high": bar.high,
                    "low": bar.low,
                    "close": bar.close,
                    "volume": bar.volume,
                    "provider": bar.provider,
                    "adjusted": bar.adjusted,
                }
                for bar in bars
            ],
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        self.logger.info("yfinance_history.write_raw.success", symbol=symbol, path=str(path), rows=len(bars))
        return path

    def _write_processed(self, symbol: str, bars: list[Bar]) -> Path:
        path = self.layout.processed_symbol_path(self.client.provider_name, "bars", symbol)
        path.parent.mkdir(parents=True, exist_ok=True)
        frame = pd.DataFrame(
            [
                {
                    "symbol": bar.symbol,
                    "timestamp": bar.timestamp,
                    "open": bar.open,
                    "high": bar.high,
                    "low": bar.low,
                    "close": bar.close,
                    "volume": bar.volume,
                    "provider": bar.provider,
                    "adjusted": bar.adjusted,
                }
                for bar in bars
            ]
        )
        if frame.empty:
            if not path.exists():
                frame.to_parquet(path, index=False)
            self.logger.info("yfinance_history.write_processed.success", symbol=symbol, path=str(path), rows=0)
            return path

        if path.exists():
            existing = pd.read_parquet(path)
            frame = pd.concat([existing, frame], ignore_index=True)

        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
        frame = frame.sort_values("timestamp").drop_duplicates(subset=["symbol", "timestamp"], keep="last")
        frame.to_parquet(path, index=False)
        self.logger.info("yfinance_history.write_processed.success", symbol=symbol, path=str(path), rows=len(frame))
        return path


def _derive_incremental_start(cursor: str | None) -> date | None:
    if not cursor:
        return None
    return date.fromisoformat(cursor) + timedelta(days=1)


def _derive_initial_history_start(end: date | None, years: int) -> date:
    anchor = end - timedelta(days=1) if end else _now_beijing().date()
    try:
        return anchor.replace(year=anchor.year - years)
    except ValueError:
        return anchor.replace(month=2, day=28, year=anchor.year - years)


def _full_history_start() -> date:
    return date(1900, 1, 1)


def _processed_coverage(path: Path) -> dict[str, str | int | None]:
    if not path.exists():
        return {"earliest_date": None, "latest_date": None, "total_rows": 0}
    try:
        frame = pd.read_parquet(path, columns=["timestamp"])
    except Exception:  # noqa: BLE001 - coverage is diagnostic and should not fail ingestion.
        return {"earliest_date": None, "latest_date": None, "total_rows": 0}
    if frame.empty or "timestamp" not in frame:
        return {"earliest_date": None, "latest_date": None, "total_rows": 0}
    timestamps = pd.to_datetime(frame["timestamp"], utc=True)
    return {
        "earliest_date": timestamps.min().date().isoformat(),
        "latest_date": timestamps.max().date().isoformat(),
        "total_rows": int(len(frame.index)),
    }


def _now_beijing() -> datetime:
    return now_beijing()
