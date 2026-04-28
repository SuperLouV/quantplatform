"""Helpers for UI APIs: pools, snapshots, history, and search."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date, datetime
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
from quant_platform.services.operation_log import OperationLogger, operation_log_root
from quant_platform.services.stock_snapshot_batch import StockSnapshotBatchService
from quant_platform.screeners import MarketScanner
from quant_platform.time_utils import iso_beijing, latest_expected_us_market_data_date, to_us_eastern

SCANNER_REQUIRED_INDICATORS = {
    "ret_20d_skip5",
    "ret_60d_skip5",
    "ret_120d_skip5",
    "rsi_14_delta_5d",
    "volume_zscore_60",
    "trend_distance_sma50_atr14",
}


class UIDataService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.artifacts = bootstrap_local_state(settings)
        self.snapshot_batch = StockSnapshotBatchService(settings)
        self.client = self.snapshot_batch.client
        self.ai_analysis = AIAnalysisService()
        self.indicator_engine = IndicatorEngine()
        self.market_events = MarketEventService(settings)
        self.market_scanner = MarketScanner()
        self.logger = OperationLogger(operation_log_root(settings), "ui_data")

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
        self.logger.info("ui.pool_dashboard.start", pool_id=pool_id)
        try:
            pool = self.snapshot_batch.load_pool(self._find_pool_path(pool_id))
            snapshots = [
                self.load_or_fetch_snapshot(symbol, pool_id=pool.pool_id, allow_auto_refresh=False)
                for symbol in pool.symbols
            ]
            payload = {
                "generated_at": self._now_iso(),
                "timezone": "Asia/Shanghai",
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
            self.logger.info("ui.pool_dashboard.success", pool_id=pool.pool_id, symbols=len(pool.symbols))
            return payload
        except Exception as exc:
            self.logger.error("ui.pool_dashboard.error", pool_id=pool_id, error=str(exc))
            raise

    def load_or_fetch_snapshot(
        self,
        symbol: str,
        *,
        pool_id: str | None = None,
        force_refresh: bool = False,
        allow_auto_refresh: bool = True,
    ) -> dict[str, object]:
        path = self.artifacts.layout.stock_snapshot_path(symbol, "json")
        if path.exists() and not force_refresh:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if pool_id and pool_id not in payload.get("pool_ids", []):
                payload["pool_ids"] = list(dict.fromkeys([*payload.get("pool_ids", []), pool_id]))
            if allow_auto_refresh and self._snapshot_needs_market_close_refresh(payload):
                self.logger.info(
                    "ui.snapshot.cache_stale",
                    symbol=symbol,
                    pool_id=pool_id,
                    path=str(path),
                    latest_history_date_us=payload.get("latest_history_date_us"),
                    target_market_date_us=latest_expected_us_market_data_date().isoformat(),
                    as_of=payload.get("as_of"),
                )
            else:
                if allow_auto_refresh:
                    self._attach_chart_history_indicators_if_missing(symbol, payload)
                    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
                self.logger.info(
                    "ui.snapshot.cache_hit",
                    symbol=symbol,
                    pool_id=pool_id,
                    path=str(path),
                    as_of=payload.get("as_of"),
                    latest_history_date_us=payload.get("latest_history_date_us"),
                    indicators=bool(payload.get("indicators")),
                    allow_auto_refresh=allow_auto_refresh,
                )
                return localize_snapshot_payload(payload)

        pool_ids = [pool_id] if pool_id else []
        if path.exists():
            existing = json.loads(path.read_text(encoding="utf-8"))
            pool_ids = list(dict.fromkeys([*existing.get("pool_ids", []), *pool_ids]))

        self.logger.info("ui.snapshot.refresh.start", symbol=symbol, pool_id=pool_id, force_refresh=force_refresh)
        try:
            quote = self._fetch_quote_snapshot_with_history_overlay(symbol)
            snapshot = self.snapshot_batch.create_snapshot_from_quote(symbol, pool_ids=pool_ids, quote=quote)
            self.snapshot_batch.attach_local_indicators(snapshot)
            written_path = self.snapshot_batch.write_snapshot(snapshot)
            payload = self.snapshot_batch.serialize_snapshot(snapshot)
            self.logger.info(
                "ui.snapshot.refresh.success",
                symbol=symbol,
                pool_ids=pool_ids,
                path=str(written_path),
                status=snapshot.screening_status,
                as_of=payload.get("as_of"),
                latest_history_date_us=payload.get("latest_history_date_us"),
            )
            return localize_snapshot_payload(payload)
        except Exception as exc:
            self.logger.error("ui.snapshot.refresh.error", symbol=symbol, pool_id=pool_id, error=str(exc))
            raise

    def history(self, symbol: str, period: str = "6mo", interval: str = "1d") -> dict[str, object]:
        self.logger.info("ui.history.fetch.start", symbol=symbol, period=period, interval=interval)
        try:
            points = self.client.fetch_chart_history(symbol, period=period, interval=interval)
            self.logger.info("ui.history.fetch.success", symbol=symbol, period=period, interval=interval, points=len(points))
            return {
                "symbol": symbol,
                "period": period,
                "interval": interval,
                "points": points,
            }
        except Exception as exc:
            self.logger.error("ui.history.fetch.error", symbol=symbol, period=period, interval=interval, error=str(exc))
            raise

    def analysis(self, symbol: str, *, pool_id: str | None = None) -> dict[str, object]:
        self.logger.info("ui.analysis.start", symbol=symbol, pool_id=pool_id)
        try:
            snapshot_payload = self.load_or_fetch_snapshot(symbol, pool_id=pool_id)
            history = self.client.fetch_chart_history(symbol, period="6mo", interval="1d")
            snapshot = self.snapshot_batch.create_snapshot_from_quote(
                symbol=symbol,
                pool_ids=list(snapshot_payload.get("pool_ids", [])),
                quote=snapshot_payload,
            )
            analysis = self.ai_analysis.create_simple_market_analysis(snapshot, history)
            payload = {
                "analysis_id": analysis.analysis_id,
                "target_id": analysis.target_id,
                "risk_level": analysis.risk_level,
                "recommendation": analysis.recommendation,
                "summary": analysis.summary,
                "key_points": analysis.key_points,
                "warnings": analysis.warnings,
                "generated_at": analysis.generated_at.isoformat() if analysis.generated_at else None,
            }
            self.logger.info(
                "ui.analysis.success",
                symbol=symbol,
                risk_level=analysis.risk_level,
                recommendation=analysis.recommendation,
                history_points=len(history),
            )
            return payload
        except Exception as exc:
            self.logger.error("ui.analysis.error", symbol=symbol, pool_id=pool_id, error=str(exc))
            raise

    def scanner(self, pool_id: str) -> dict[str, object]:
        self.logger.info("ui.scanner.start", pool_id=pool_id)
        try:
            dashboard = self.load_pool_dashboard(pool_id)
            snapshots = [
                self._attach_local_scanner_indicators(snapshot)
                for snapshot in dashboard.get("snapshots", [])
                if isinstance(snapshot, dict)
            ]
            result = self.market_scanner.scan_snapshots(snapshots)

            payload = {
                "generated_at": self._now_iso(),
                "timezone": "Asia/Shanghai",
                "market_date_us": _scanner_market_date_us(result.candidates),
                "market_timezone": "America/New_York",
                "pool": dashboard.get("pool", {}),
                "summary": asdict(result.summary),
                "candidates": [_scan_candidate_payload(candidate) for candidate in result.candidates],
            }
            scan_result_path = self._write_scan_result(pool_id, payload)
            payload["scan_result_path"] = str(scan_result_path)
            self.logger.info(
                "ui.scanner.success",
                pool_id=pool_id,
                market_date_us=payload["market_date_us"],
                path=str(scan_result_path),
                candidates=len(result.candidates),
            )
            return payload
        except Exception as exc:
            self.logger.error("ui.scanner.error", pool_id=pool_id, error=str(exc))
            raise

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
        self.logger.info("ui.market_events.load.start", start=start, end=end)
        try:
            events = self.market_events.load_events(start=start, end=end)
            self.logger.info("ui.market_events.load.success", start=start, end=end, events=len(events))
            return {
                "generated_at": iso_beijing(),
                "timezone": "Asia/Shanghai",
                "events": events,
            }
        except Exception as exc:
            self.logger.error("ui.market_events.load.error", start=start, end=end, error=str(exc))
            raise

    def _attach_local_scanner_indicators(self, payload: dict[str, object]) -> dict[str, object]:
        symbol = str(payload.get("symbol") or "")
        indicators = payload.get("indicators") if isinstance(payload.get("indicators"), dict) else {}
        if not symbol or not isinstance(indicators, dict):
            return payload
        if all(indicators.get(key) is not None for key in SCANNER_REQUIRED_INDICATORS):
            return payload

        path = self.artifacts.layout.processed_symbol_path(self.client.provider_name, "bars", symbol)
        if not path.exists():
            self.logger.info("ui.scanner.indicators.skipped", symbol=symbol, reason="missing_bars", path=str(path))
            return payload

        try:
            computation = self.indicator_engine.compute_from_parquet(path)
        except Exception as exc:  # noqa: BLE001 - scanner should degrade when local data is malformed.
            self.logger.error("ui.scanner.indicators.error", symbol=symbol, path=str(path), error=str(exc))
            return payload

        payload["indicators"] = {
            **indicators,
            **computation.latest,
        }
        self.logger.info(
            "ui.scanner.indicators.success",
            symbol=symbol,
            path=str(path),
            columns=len(computation.latest),
        )
        return payload

    def _write_scan_result(self, pool_id: str, payload: dict[str, object]) -> Path:
        market_date_us = str(payload.get("market_date_us") or "unknown")
        path = self.settings.storage.reference_dir / "system" / "scan_results" / f"{pool_id}_{market_date_us}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        payload_to_write = {**payload, "scan_result_path": str(path)}
        path.write_text(json.dumps(payload_to_write, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def _find_pool_path(self, pool_id: str) -> Path | None:
        base = self.artifacts.layout.storage.reference_dir / "system" / "stock_pools"
        matches = list(base.glob(f"*/{pool_id}.json"))
        return matches[0] if matches else None

    def _attach_chart_history_indicators_if_missing(self, symbol: str, payload: dict[str, object]) -> None:
        indicators = payload.get("indicators")
        if isinstance(indicators, dict) and any(value is not None for value in indicators.values()):
            return

        try:
            self.logger.info("ui.indicators.enrich.start", symbol=symbol, source="chart_history")
            history = self.client.fetch_chart_history(symbol, period="1y", interval="1d")
            if len(history) < 20:
                _append_screening_reason(payload, "warning:insufficient_history:图表历史不足 20 根，未生成交易指标。")
                self.logger.info("ui.indicators.enrich.skipped", symbol=symbol, reason="insufficient_history", points=len(history))
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
            self.logger.info("ui.indicators.enrich.success", symbol=symbol, points=len(history), as_of=latest_timestamp.isoformat())
        except Exception as exc:  # noqa: BLE001 - UI should degrade instead of breaking on indicator enrichment.
            _append_screening_reason(payload, f"warning:indicator_history_error:图表历史指标生成失败：{exc}")
            self.logger.error("ui.indicators.enrich.error", symbol=symbol, error=str(exc))

    def _fetch_quote_snapshot_with_history_overlay(self, symbol: str) -> dict[str, object]:
        quote = self.client.fetch_quote_snapshot(symbol)
        try:
            history = self.client.fetch_chart_history(symbol, period="5d", interval="1d")
            self._apply_latest_daily_bar(symbol, quote, history)
        except Exception as exc:  # noqa: BLE001 - quote refresh should still work if history overlay is unavailable.
            self.logger.error("ui.snapshot.history_overlay.error", symbol=symbol, error=str(exc))
        return quote

    def _apply_latest_daily_bar(
        self,
        symbol: str,
        quote: dict[str, object],
        history: list[dict[str, object]],
    ) -> None:
        rows = [row for row in history if row.get("timestamp") and row.get("close") is not None]
        if not rows:
            self.logger.info("ui.snapshot.history_overlay.skipped", symbol=symbol, reason="empty_history")
            return

        rows = sorted(rows, key=lambda row: str(row.get("timestamp")))
        latest = rows[-1]
        previous = rows[-2] if len(rows) > 1 else None
        latest_close = _optional_float(latest.get("close"))
        previous_close = _optional_float(previous.get("close")) if previous else _optional_float(quote.get("previous_close"))
        latest_history_date_us = _history_market_date_us(latest.get("timestamp"))

        quote["open_price"] = _optional_float(latest.get("open"))
        quote["high_price"] = _optional_float(latest.get("high"))
        quote["low_price"] = _optional_float(latest.get("low"))
        quote["latest_close"] = latest_close
        quote["latest_volume"] = _optional_float(latest.get("volume"))
        quote["previous_close"] = previous_close
        quote["latest_history_date_us"] = latest_history_date_us
        quote["snapshot_refreshed_at_beijing"] = iso_beijing()
        quote["market_timezone"] = "America/New_York"

        market_state = str(quote.get("market_state") or "").upper()
        if market_state not in {"REGULAR", "PRE", "PREPRE", "POST", "POSTPOST"}:
            quote["current_price"] = latest_close
            quote["regular_market_price"] = latest_close

        if latest_close is not None and previous_close not in (None, 0):
            quote["change_percent"] = ((latest_close - previous_close) / previous_close) * 100

        self.logger.info(
            "ui.snapshot.history_overlay.success",
            symbol=symbol,
            latest_history_date_us=latest_history_date_us,
            latest_close=latest_close,
            previous_close=previous_close,
            market_state=quote.get("market_state"),
        )

    def _snapshot_needs_market_close_refresh(self, payload: dict[str, object]) -> bool:
        latest_history_date = payload.get("latest_history_date_us")
        target_market_date = latest_expected_us_market_data_date().isoformat()
        if not latest_history_date:
            return True
        if str(latest_history_date) < target_market_date:
            return True
        if payload.get("latest_close") is None:
            return True
        return False

    @staticmethod
    def _now_iso() -> str:
        return iso_beijing()


def _append_screening_reason(payload: dict[str, object], reason: str) -> None:
    reasons = payload.get("screening_reasons")
    if not isinstance(reasons, list):
        reasons = []
    if reason not in reasons:
        reasons.append(reason)
    payload["screening_reasons"] = reasons


def _scan_candidate_payload(candidate) -> dict[str, object]:
    payload = asdict(candidate)
    payload["reasons"] = candidate.reasons[:5]
    return payload


def _scanner_market_date_us(candidates) -> str | None:
    dates = [
        candidate.latest_history_date_us
        for candidate in candidates
        if getattr(candidate, "latest_history_date_us", None)
    ]
    if not dates:
        return None
    return max(str(value) for value in dates)


def _history_market_date_us(value: object) -> str | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(str(value))
    return to_us_eastern(parsed).date().isoformat()


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
