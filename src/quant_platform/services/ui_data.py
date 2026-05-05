"""Helpers for UI APIs: pools, snapshots, history, and search."""

from __future__ import annotations

import json
import math
from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pandas as pd

from quant_platform.config import Settings
from quant_platform.clients.longbridge_cli import LongbridgeCLIClient
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
from quant_platform.time_utils import iso_beijing, latest_expected_us_market_data_date, now_beijing, to_us_eastern

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
        self.longbridge_client = LongbridgeCLIClient.from_data_config(settings.data)
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
        existing: dict[str, object] = {}
        if path.exists():
            existing = json.loads(path.read_text(encoding="utf-8"))
            pool_ids = list(dict.fromkeys([*existing.get("pool_ids", []), *pool_ids]))

        self.logger.info("ui.snapshot.refresh.start", symbol=symbol, pool_id=pool_id, force_refresh=force_refresh)
        try:
            quote = self._fetch_quote_snapshot_with_history_overlay(symbol)
            _preserve_existing_metadata(quote, existing)
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

    def get_dashboard_data(self) -> dict[str, object]:
        self.logger.info("ui.dashboard.load.start")
        payload: dict[str, object] = {
            "generated_at": self._now_iso(),
            "timezone": "Asia/Shanghai",
            "market_overview": None,
            "macro_risk": None,
            "scheduler": None,
            "scanner_top": [],
            "positions_risk": [],
            "total_position_pct": None,
            "available_cash": None,
            "cash_ratio_pct": None,
            "pdt": None,
            "events_upcoming": [],
            "ai_summary": None,
            "daily_report_available": False,
            "daily_report_date": None,
        }
        errors: dict[str, str] = {}

        for key, loader in (
            ("market_overview", self._dashboard_market_overview),
            ("macro_risk", self._dashboard_macro_risk),
            ("scanner_top", self._dashboard_scanner_top),
            ("positions", self._dashboard_positions),
            ("events_upcoming", self._dashboard_events),
            ("ai_summary", self._dashboard_ai_summary),
            ("daily_report", self._dashboard_daily_report_meta),
        ):
            try:
                value = loader()
                if key == "positions" and isinstance(value, dict):
                    payload.update(value)
                elif key == "daily_report" and isinstance(value, dict):
                    payload.update(value)
                else:
                    payload[key] = value
            except Exception as exc:  # noqa: BLE001 - dashboard blocks must degrade independently.
                errors[key] = str(exc)
                self.logger.error("ui.dashboard.block.error", block=key, error=str(exc))

        if errors:
            payload["errors"] = errors
        self.logger.info(
            "ui.dashboard.load.success",
            scanner_top=len(payload.get("scanner_top") or []),
            positions=len(payload.get("positions_risk") or []),
            events=len(payload.get("events_upcoming") or []),
            has_report=payload.get("daily_report_available"),
        )
        return payload

    def latest_daily_report(self, *, report_date: date | None = None) -> dict[str, object]:
        reports_dir = self.settings.storage.processed_dir.parent / "reports"
        if report_date is not None:
            candidates = [
                reports_dir / f"daily_{report_date.isoformat()}.md",
                *sorted(reports_dir.glob(f"daily_*_{report_date.isoformat()}.md")),
            ]
            path = next((item for item in candidates if item.exists()), None)
        else:
            path = _latest_file(reports_dir, "daily*.md")
        if path is None:
            raise FileNotFoundError("Daily report not found.")
        content = path.read_text(encoding="utf-8")
        return {
            "date": _daily_report_date(path),
            "pool_id": _daily_report_pool_id(path),
            "content_markdown": content,
            "generated_at": datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).astimezone().isoformat(),
            "path": str(path),
        }

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
        quote = self._fetch_quote_snapshot(symbol)
        if quote.get("quote_provider") == "longbridge_cli":
            return quote
        try:
            history = self.client.fetch_chart_history(symbol, period="5d", interval="1d")
            self._apply_latest_daily_bar(symbol, quote, history)
        except Exception as exc:  # noqa: BLE001 - quote refresh should still work if history overlay is unavailable.
            self.logger.error("ui.snapshot.history_overlay.error", symbol=symbol, error=str(exc))
        return quote

    def _fetch_quote_snapshot(self, symbol: str) -> dict[str, object]:
        provider = self.settings.data.quote_provider
        if provider in {"auto", "longbridge_cli"}:
            try:
                self.logger.info("ui.snapshot.quote_provider.start", symbol=symbol, provider="longbridge_cli")
                quote = self.longbridge_client.fetch_quote_snapshot(symbol)
                self.logger.info(
                    "ui.snapshot.quote_provider.success",
                    symbol=symbol,
                    provider="longbridge_cli",
                    market_state=quote.get("market_state"),
                    current_price=quote.get("current_price"),
                    latest_history_date_us=quote.get("latest_history_date_us"),
                )
                return quote
            except Exception as exc:  # noqa: BLE001 - auto mode should fall back to yfinance.
                self.logger.error("ui.snapshot.quote_provider.error", symbol=symbol, provider="longbridge_cli", error=str(exc))
                if provider == "longbridge_cli":
                    raise

        self.logger.info("ui.snapshot.quote_provider.start", symbol=symbol, provider=self.client.provider_name)
        quote = self.client.fetch_quote_snapshot(symbol)
        quote["quote_provider"] = self.client.provider_name
        quote["quote_provider_status"] = "fallback" if provider == "auto" else "success"
        self.logger.info(
            "ui.snapshot.quote_provider.success",
            symbol=symbol,
            provider=self.client.provider_name,
            status=quote.get("quote_provider_status"),
            market_state=quote.get("market_state"),
            current_price=quote.get("current_price"),
            latest_history_date_us=quote.get("latest_history_date_us"),
        )
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

    def _dashboard_market_overview(self) -> dict[str, object] | None:
        spy = self._latest_market_symbol_state("SPY")
        qqq = self._latest_market_symbol_state("QQQ")
        vix = self._latest_market_symbol_state("^VIX")
        regime = _market_regime(spy, qqq, vix)
        return {
            "spy": spy,
            "qqq": qqq,
            "vix": vix,
            "regime": regime,
        }

    def _dashboard_macro_risk(self) -> dict[str, object] | None:
        report_path = _latest_file(self.settings.storage.processed_dir.parent / "reports" / "macro_risk", "macro_risk_*.json")
        if report_path is None:
            return None
        payload = _load_json(report_path) or {}
        overview = payload.get("market_overview") if isinstance(payload.get("market_overview"), dict) else {}
        overview_summary = overview.get("summary") if isinstance(overview.get("summary"), dict) else {}
        return {
            "generated_at_beijing": payload.get("generated_at_beijing"),
            "market_date_us": payload.get("market_date_us"),
            "risk_state": payload.get("risk_state"),
            "sentiment_state": payload.get("sentiment_state"),
            "scanner_filter_hint": payload.get("scanner_filter_hint"),
            "vix_state": overview_summary.get("vix_state"),
            "news_item_count": len(payload.get("news_items") or []) if isinstance(payload.get("news_items"), list) else 0,
            "warnings": payload.get("warnings") if isinstance(payload.get("warnings"), list) else [],
        }

    def _latest_market_symbol_state(self, symbol: str) -> dict[str, object] | None:
        snapshot_path = self.settings.storage.processed_dir / "snapshots" / f"{symbol}.json"
        if snapshot_path.exists():
            payload = _load_json(snapshot_path) or {}
            price = _optional_float(payload.get("current_price") or payload.get("latest_close"))
            previous = _optional_float(payload.get("previous_close"))
            return {
                "symbol": symbol,
                "price": price,
                "change_pct": _optional_float(payload.get("change_percent")) or _pct_change(price, previous),
                "as_of": payload.get("latest_history_date_us") or payload.get("as_of"),
                "state": _vix_state(price) if symbol == "^VIX" else _trend_state_from_snapshot(payload, price),
            }

        bars_path = self.artifacts.layout.processed_symbol_path(self.client.provider_name, "bars", symbol)
        if not bars_path.exists():
            return None
        frame = pd.read_parquet(bars_path)
        if frame.empty:
            return None
        computed = self.indicator_engine.compute(frame).series
        latest = computed.iloc[-1]
        previous = computed.iloc[-2] if len(computed.index) >= 2 else None
        price = _optional_float(latest.get("close"))
        previous_close = _optional_float(previous.get("close")) if previous is not None else None
        sma50 = _optional_float(latest.get("sma_50"))
        return {
            "symbol": symbol,
            "price": price,
            "change_pct": _pct_change(price, previous_close),
            "as_of": _history_market_date_us(latest.get("timestamp")),
            "sma50_state": _price_vs_sma(price, sma50),
            "state": _vix_state(price) if symbol == "^VIX" else _trend_state(price, sma50),
        }

    def _dashboard_scanner_top(self) -> list[dict[str, object]]:
        scan_path = _latest_file(self.settings.storage.reference_dir / "system" / "scan_results", "*.json")
        if scan_path is None:
            return []
        payload = _load_json(scan_path) or {}
        candidates = [item for item in payload.get("candidates", []) if isinstance(item, dict)]
        candidates = sorted(candidates, key=lambda item: _optional_float(item.get("score")) or 0, reverse=True)
        result: list[dict[str, object]] = []
        for item in candidates[:6]:
            signals = item.get("signals") if isinstance(item.get("signals"), list) else []
            result.append(
                {
                    "symbol": item.get("symbol"),
                    "company_name": item.get("company_name"),
                    "price": _optional_float(item.get("price")),
                    "change_pct": _optional_float(item.get("change_percent")),
                    "score": _optional_float(item.get("score")),
                    "action": item.get("action"),
                    "risk_level": item.get("risk_level"),
                    "signals": _signal_labels(signals, item.get("reasons")),
                    "atr_stop_price": _candidate_atr_stop(item),
                    "latest_history_date_us": item.get("latest_history_date_us"),
                }
            )
        return result

    def _dashboard_positions(self) -> dict[str, object]:
        report_path = _latest_file(self.settings.storage.processed_dir.parent / "reports" / "account_health", "account_health_*.json")
        if report_path is None:
            return {"positions_risk": []}
        payload = _load_json(report_path) or {}
        account = payload.get("account") if isinstance(payload.get("account"), dict) else {}
        risk = payload.get("risk_assessment") if isinstance(payload.get("risk_assessment"), dict) else {}
        positions = [item for item in risk.get("positions", []) if isinstance(item, dict)]
        positions = sorted(positions, key=_position_priority, reverse=True)
        return {
            "positions_risk": [_position_risk_payload(item) for item in positions[:8]],
            "total_position_pct": _invested_pct(risk),
            "available_cash": _optional_float(account.get("available_cash") or risk.get("cash")),
            "cash_ratio_pct": _optional_float(risk.get("cash_ratio_pct")),
            "pdt": risk.get("pdt") if isinstance(risk.get("pdt"), dict) else None,
            "portfolio_health_state": risk.get("health_state"),
            "portfolio_warnings": (risk.get("warnings") or [])[:5] if isinstance(risk.get("warnings"), list) else [],
        }

    def _dashboard_events(self) -> list[dict[str, object]]:
        now_date = now_beijing().date()
        events = self.market_events.load_events(start=now_date, end=now_date + timedelta(days=14))
        result: list[dict[str, object]] = []
        for item in events[:8]:
            event_time = item.get("event_time")
            result.append(
                {
                    "date": str(event_time)[:10] if event_time else None,
                    "title": item.get("title"),
                    "severity": item.get("importance") or item.get("severity"),
                    "source": item.get("source"),
                    "category": item.get("category"),
                }
            )
        return result

    def _dashboard_ai_summary(self) -> str | None:
        report_path = _latest_file(self.settings.storage.processed_dir.parent / "reports" / "ai_analysis", "*.json")
        if report_path is None:
            return None
        payload = _load_json(report_path) or {}
        model = payload.get("model") if isinstance(payload.get("model"), dict) else {}
        markdown = str(model.get("markdown") or "").strip()
        if markdown:
            return _first_meaningful_line(markdown)
        prompt = payload.get("prompt_payload") if isinstance(payload.get("prompt_payload"), dict) else {}
        context = prompt.get("structured_context") if isinstance(prompt.get("structured_context"), dict) else {}
        risk = context.get("risk_summary") if isinstance(context.get("risk_summary"), dict) else {}
        recommendations = risk.get("recommendations") if isinstance(risk.get("recommendations"), list) else []
        if recommendations:
            return "；".join(str(item) for item in recommendations[:2])
        summary = context.get("account_summary") if isinstance(context.get("account_summary"), dict) else {}
        if summary:
            return (
                f"账户风险状态 {summary.get('risk_level') or '--'}，"
                f"现金 {summary.get('available_cash') or '--'}，"
                f"持仓数 {summary.get('position_count') or '--'}。"
            )
        return None

    def _dashboard_daily_report_meta(self) -> dict[str, object]:
        report_path = _latest_file(self.settings.storage.processed_dir.parent / "reports", "daily*.md")
        return {
            "daily_report_available": report_path is not None,
            "daily_report_date": _daily_report_date(report_path) if report_path else None,
        }


def _append_screening_reason(payload: dict[str, object], reason: str) -> None:
    reasons = payload.get("screening_reasons")
    if not isinstance(reasons, list):
        reasons = []
    if reason not in reasons:
        reasons.append(reason)
    payload["screening_reasons"] = reasons


def _preserve_existing_metadata(quote: dict[str, object], existing: dict[str, object]) -> None:
    if not existing:
        return
    for key in (
        "company_name",
        "sector",
        "industry",
        "currency",
        "market_cap",
        "avg_dollar_volume",
        "trailing_pe",
        "forward_pe",
        "next_earnings_date",
        "exchange",
    ):
        if quote.get(key) in (None, "") and existing.get(key) not in (None, ""):
            quote[key] = existing[key]


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
        result = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(result):
        return None
    return result


def _load_json(path: Path) -> dict[str, object] | None:
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else None


def _latest_file(base: Path, pattern: str) -> Path | None:
    if not base.exists():
        return None
    matches = [path for path in base.glob(pattern) if path.is_file()]
    if not matches:
        return None
    return max(matches, key=lambda path: (path.stat().st_mtime, path.name))


def _pct_change(value: float | None, base: float | None) -> float | None:
    if value is None or base in (None, 0):
        return None
    return ((value - base) / base) * 100


def _price_vs_sma(price: float | None, sma: float | None) -> str | None:
    if price is None or sma is None:
        return None
    return "above" if price >= sma else "below"


def _trend_state(price: float | None, sma50: float | None) -> str:
    state = _price_vs_sma(price, sma50)
    if state == "above":
        return "偏多"
    if state == "below":
        return "偏空"
    return "未知"


def _trend_state_from_snapshot(payload: dict[str, object], price: float | None) -> str:
    indicators = payload.get("indicators") if isinstance(payload.get("indicators"), dict) else {}
    sma50 = _optional_float(indicators.get("sma_50")) if isinstance(indicators, dict) else None
    return _trend_state(price, sma50)


def _vix_state(price: float | None) -> str:
    if price is None:
        return "未知"
    if price >= 25:
        return "高波动"
    if price >= 18:
        return "偏紧张"
    return "正常"


def _market_regime(
    spy: dict[str, object] | None,
    qqq: dict[str, object] | None,
    vix: dict[str, object] | None,
) -> str:
    spy_state = str((spy or {}).get("state") or "")
    qqq_state = str((qqq or {}).get("state") or "")
    vix_price = _optional_float((vix or {}).get("price"))
    if vix_price is not None and vix_price >= 25:
        return "偏空"
    if spy_state == "偏多" and qqq_state == "偏多" and (vix_price is None or vix_price < 18):
        return "偏多"
    if spy_state == "偏空" and qqq_state == "偏空":
        return "偏空"
    return "中性"


def _signal_labels(signals: list[object], reasons: object) -> list[str]:
    labels: list[str] = []
    for signal in signals:
        if not isinstance(signal, dict):
            continue
        reason = signal.get("reason")
        state = signal.get("state")
        if reason:
            labels.append(str(reason))
        elif state:
            labels.append(str(state))
        if len(labels) >= 3:
            break
    if not labels and isinstance(reasons, list):
        labels = [str(item) for item in reasons[:3]]
    return labels


def _candidate_atr_stop(item: dict[str, object]) -> float | None:
    price = _optional_float(item.get("price"))
    if price is None:
        return None
    for signal in item.get("signals", []) if isinstance(item.get("signals"), list) else []:
        if not isinstance(signal, dict):
            continue
        evidence = signal.get("evidence") if isinstance(signal.get("evidence"), dict) else {}
        atr = _optional_float(evidence.get("atr_14")) if isinstance(evidence, dict) else None
        if atr is not None:
            return max(0.0, price - 2 * atr)
    return None


def _position_priority(item: dict[str, object]) -> float:
    score = _optional_float(item.get("weight_pct")) or 0
    atr_stop = item.get("atr_stop") if isinstance(item.get("atr_stop"), dict) else {}
    stop_distance = _optional_float(atr_stop.get("stop_distance_pct")) if isinstance(atr_stop, dict) else None
    if item.get("concentration_status") == "breach":
        score += 100
    if item.get("max_loss_status") not in {None, "ok"}:
        score += 80
    if stop_distance is not None and stop_distance <= 3:
        score += 60
    return score


def _position_risk_payload(item: dict[str, object]) -> dict[str, object]:
    atr_stop = item.get("atr_stop") if isinstance(item.get("atr_stop"), dict) else {}
    status = "健康"
    if item.get("concentration_status") == "breach" or item.get("max_loss_status") not in {None, "ok"}:
        status = "警告"
    stop_distance = _optional_float(atr_stop.get("stop_distance_pct")) if isinstance(atr_stop, dict) else None
    if stop_distance is not None and stop_distance <= 3:
        status = "临近止损"
    return {
        "symbol": item.get("symbol"),
        "name": item.get("name"),
        "status": status,
        "current_price": _optional_float(item.get("current_price")),
        "weight_pct": _optional_float(item.get("weight_pct")),
        "stop_price": _optional_float(atr_stop.get("stop_price")) if isinstance(atr_stop, dict) else None,
        "stop_distance_pct": stop_distance,
        "unrealized_pl_pct": _optional_float(item.get("unrealized_pl_pct")),
        "flags": item.get("flags") if isinstance(item.get("flags"), list) else [],
    }


def _invested_pct(risk: dict[str, object]) -> float | None:
    invested = _optional_float(risk.get("invested_value"))
    equity = _optional_float(risk.get("equity"))
    if invested is None or equity in (None, 0):
        return None
    return invested / equity * 100


def _first_meaningful_line(markdown: str) -> str:
    for raw_line in markdown.splitlines():
        line = raw_line.strip().strip("#").strip()
        if line:
            return line
    return markdown[:240]


def _daily_report_date(path: Path | None) -> str | None:
    if path is None:
        return None
    for part in reversed(path.stem.split("_")):
        try:
            date.fromisoformat(part)
            return part
        except ValueError:
            continue
    return None


def _daily_report_pool_id(path: Path) -> str | None:
    parts = path.stem.split("_")
    if len(parts) > 2 and parts[0] == "daily":
        return "_".join(parts[1:-1])
    return None
