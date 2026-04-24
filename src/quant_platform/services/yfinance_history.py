"""Incremental yfinance history update service."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pandas as pd

from quant_platform.clients.yfinance import YFinanceClient
from quant_platform.config import Settings
from quant_platform.core.models import Bar, DataRequest
from quant_platform.services.bootstrap import bootstrap_local_state
from quant_platform.storage import DataLayout, SQLiteStateStore, UpdateRunRecord


@dataclass(slots=True)
class YFinanceHistoryUpdateResult:
    symbol: str
    rows_written: int
    raw_path: Path
    processed_path: Path
    cursor: str | None


class YFinanceHistoryUpdater:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        artifacts = bootstrap_local_state(settings)
        self.layout: DataLayout = artifacts.layout
        self.state_store: SQLiteStateStore = artifacts.state_store
        self.client = YFinanceClient.from_data_config(settings.data)

    def update_symbol(
        self,
        symbol: str,
        *,
        start: date | None = None,
        end: date | None = None,
        interval: str = "1d",
        adjusted: bool = True,
    ) -> YFinanceHistoryUpdateResult:
        dataset = "bars"
        run_started = _utcnow()
        checkpoint = self.state_store.get_checkpoint(self.client.provider_name, dataset, symbol)
        effective_start = start or _derive_incremental_start(checkpoint.cursor)
        request = DataRequest(symbol=symbol, start=effective_start, end=end, interval=interval, adjusted=adjusted)

        self.state_store.mark_attempt(
            self.client.provider_name,
            dataset,
            symbol,
            cursor=checkpoint.cursor if checkpoint else None,
            note=f"start={effective_start.isoformat() if effective_start else 'full'} interval={interval}",
        )

        try:
            bars = self.client.fetch_bars(request)
            raw_path = self._write_raw(symbol, request, bars)
            processed_path = self._write_processed(symbol, bars)
            cursor = bars[-1].timestamp.date().isoformat() if bars else (checkpoint.cursor if checkpoint else None)

            self.state_store.mark_success(
                self.client.provider_name,
                dataset,
                symbol,
                cursor=cursor,
                note=f"rows={len(bars)}",
            )
            self.state_store.record_run(
                UpdateRunRecord(
                    provider=self.client.provider_name,
                    dataset=dataset,
                    symbol=symbol,
                    started_at=run_started,
                    finished_at=_utcnow(),
                    status="success",
                    rows_written=len(bars),
                    note=f"raw={raw_path.name} processed={processed_path.name}",
                )
            )
            return YFinanceHistoryUpdateResult(
                symbol=symbol,
                rows_written=len(bars),
                raw_path=raw_path,
                processed_path=processed_path,
                cursor=cursor,
            )
        except Exception as exc:
            self.state_store.mark_failure(
                self.client.provider_name,
                dataset,
                symbol,
                cursor=checkpoint.cursor if checkpoint else None,
                note=str(exc),
            )
            self.state_store.record_run(
                UpdateRunRecord(
                    provider=self.client.provider_name,
                    dataset=dataset,
                    symbol=symbol,
                    started_at=run_started,
                    finished_at=_utcnow(),
                    status="failed",
                    rows_written=0,
                    note=str(exc),
                )
            )
            raise

    def _write_raw(self, symbol: str, request: DataRequest, bars: list[Bar]) -> Path:
        partition = _utcnow().strftime("%Y%m%dT%H%M%SZ")
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
            "fetched_at": _utcnow().isoformat(),
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
            return path

        if path.exists():
            existing = pd.read_parquet(path)
            frame = pd.concat([existing, frame], ignore_index=True)

        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
        frame = frame.sort_values("timestamp").drop_duplicates(subset=["symbol", "timestamp"], keep="last")
        frame.to_parquet(path, index=False)
        return path


def _derive_incremental_start(cursor: str | None) -> date | None:
    if not cursor:
        return None
    return date.fromisoformat(cursor) + timedelta(days=1)


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)
