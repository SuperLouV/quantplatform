"""Helpers for UI APIs: pools, snapshots, history, and search."""

from __future__ import annotations

import json
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
from quant_platform.time_utils import iso_beijing, latest_expected_us_market_data_date, to_us_eastern


class UIDataService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.artifacts = bootstrap_local_state(settings)
        self.snapshot_batch = StockSnapshotBatchService(settings)
        self.client = self.snapshot_batch.client
        self.ai_analysis = AIAnalysisService()
        self.indicator_engine = IndicatorEngine()
        self.market_events = MarketEventService(settings)
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
            candidates = [_build_scan_candidate(snapshot) for snapshot in dashboard.get("snapshots", [])]
            candidates = sorted(candidates, key=lambda item: (-int(item["score"]), str(item["symbol"])))
            action_counts: dict[str, int] = {}
            risk_counts: dict[str, int] = {}
            for candidate in candidates:
                action = str(candidate["action"])
                risk = str(candidate["risk_level"])
                action_counts[action] = action_counts.get(action, 0) + 1
                risk_counts[risk] = risk_counts.get(risk, 0) + 1

            payload = {
                "generated_at": self._now_iso(),
                "timezone": "Asia/Shanghai",
                "pool": dashboard.get("pool", {}),
                "summary": {
                    "total": len(candidates),
                    "candidate_buy": action_counts.get("候选买入", 0),
                    "watch": action_counts.get("继续观察", 0),
                    "risk_avoid": action_counts.get("风险回避", 0),
                    "insufficient_data": action_counts.get("数据不足", 0),
                    "high_risk": risk_counts.get("高", 0),
                    "medium_risk": risk_counts.get("中", 0),
                    "low_risk": risk_counts.get("低", 0),
                },
                "candidates": candidates,
            }
            self.logger.info("ui.scanner.success", pool_id=pool_id, candidates=len(candidates))
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


def _build_scan_candidate(snapshot: dict[str, object]) -> dict[str, object]:
    indicators = snapshot.get("indicators") if isinstance(snapshot.get("indicators"), dict) else {}
    assert isinstance(indicators, dict)
    price = _optional_float(snapshot.get("current_price")) or _optional_float(snapshot.get("latest_close"))
    previous_close = _optional_float(snapshot.get("previous_close"))
    change_percent = _optional_float(snapshot.get("change_percent"))
    if change_percent is None and price is not None and previous_close not in (None, 0):
        change_percent = ((price - previous_close) / previous_close) * 100

    sma20 = _optional_float(indicators.get("sma_20"))
    sma50 = _optional_float(indicators.get("sma_50"))
    sma200 = _optional_float(indicators.get("sma_200"))
    rsi14 = _optional_float(indicators.get("rsi_14"))
    macd = _optional_float(indicators.get("macd"))
    macd_signal = _optional_float(indicators.get("macd_signal"))
    volume_ratio = _optional_float(indicators.get("volume_ratio_20"))
    data_quality = _scan_data_quality(snapshot, indicators)

    trend_state, trend_score, trend_reason = _scan_trend(price, sma20, sma50, sma200)
    rsi_state, rsi_score, rsi_reason = _scan_rsi(rsi14)
    macd_state, macd_score, macd_reason = _scan_macd(macd, macd_signal)
    volume_state, volume_score, volume_reason = _scan_volume(volume_ratio)
    risk_level, risk_penalty, risk_reason = _scan_risk(snapshot, data_quality)

    score = max(0, min(100, 45 + trend_score + rsi_score + macd_score + volume_score - risk_penalty))
    action = _scan_action(score, risk_level, data_quality)
    reasons = [trend_reason, rsi_reason, macd_reason, volume_reason, risk_reason]
    reasons = [reason for reason in reasons if reason]

    return {
        "symbol": snapshot.get("symbol"),
        "company_name": snapshot.get("company_name_zh") or snapshot.get("company_name"),
        "price": price,
        "change_percent": change_percent,
        "latest_history_date_us": snapshot.get("latest_history_date_us"),
        "snapshot_refreshed_at_beijing": snapshot.get("snapshot_refreshed_at_beijing"),
        "score": round(score),
        "action": action,
        "risk_level": risk_level,
        "trend_state": trend_state,
        "rsi_state": rsi_state,
        "macd_state": macd_state,
        "volume_state": volume_state,
        "data_quality": data_quality,
        "reasons": reasons[:5],
    }


def _scan_data_quality(snapshot: dict[str, object], indicators: dict[str, object]) -> str:
    if not snapshot.get("latest_history_date_us"):
        return "缺行情日期"
    usable = any(_optional_float(indicators.get(key)) is not None for key in ("sma_20", "sma_50", "rsi_14", "macd"))
    if not usable:
        return "指标不足"
    return "正常"


def _scan_trend(price: float | None, sma20: float | None, sma50: float | None, sma200: float | None) -> tuple[str, int, str]:
    if price is None or sma20 is None or sma50 is None:
        return "数据不足", -18, "趋势数据不足"
    if sma200 is not None and price > sma20 > sma50 > sma200:
        return "多头排列", 22, "价格和均线呈多头排列"
    if price > sma20 and sma20 >= sma50:
        return "偏强", 14, "价格站上短中期均线"
    if price < sma20 and sma20 < sma50:
        return "转弱", -12, "价格跌破短期均线且短线弱于中期"
    return "震荡", 0, "趋势方向暂不明确"


def _scan_rsi(rsi14: float | None) -> tuple[str, int, str]:
    if rsi14 is None:
        return "数据不足", -10, "RSI 数据不足"
    if 45 <= rsi14 <= 65:
        return "健康", 8, "RSI 处于相对健康区间"
    if 30 <= rsi14 < 45:
        return "修复", 4, "RSI 从弱势区间修复中"
    if rsi14 < 30:
        return "超跌", -2, "RSI 低于 30，可能超跌但仍需确认"
    if rsi14 > 75:
        return "过热", -8, "RSI 高位过热"
    return "偏热", -2, "RSI 偏高，追涨风险上升"


def _scan_macd(macd: float | None, signal: float | None) -> tuple[str, int, str]:
    if macd is None or signal is None:
        return "数据不足", -8, "MACD 数据不足"
    if macd > signal:
        return "偏多", 10, "MACD 在 Signal 上方"
    if macd < signal:
        return "偏弱", -8, "MACD 在 Signal 下方"
    return "中性", 0, "MACD 与 Signal 接近"


def _scan_volume(volume_ratio: float | None) -> tuple[str, int, str]:
    if volume_ratio is None:
        return "数据不足", -4, "成交量指标不足"
    if volume_ratio >= 1.8:
        return "明显放量", 8, "成交量明显高于 20 日均量"
    if volume_ratio >= 1.2:
        return "温和放量", 5, "成交量温和放大"
    if volume_ratio < 0.7:
        return "缩量", -2, "成交量低于近期均量"
    return "正常", 0, "成交量接近近期均值"


def _scan_risk(snapshot: dict[str, object], data_quality: str) -> tuple[str, int, str]:
    if data_quality != "正常":
        return "高", 28, f"数据状态：{data_quality}"
    reasons = snapshot.get("screening_reasons")
    reason_text = " ".join(str(item) for item in reasons) if isinstance(reasons, list) else ""
    if "stale_bars" in reason_text or "future_bars" in reason_text or "error" in reason_text:
        return "高", 24, "本地数据质量存在风险提示"
    if snapshot.get("next_earnings_date"):
        return "中", 8, "存在财报日期，需确认事件风险"
    return "低", 0, "未发现明显数据或事件风险"


def _scan_action(score: float, risk_level: str, data_quality: str) -> str:
    if data_quality != "正常":
        return "数据不足"
    if risk_level == "高":
        return "风险回避"
    if score >= 72:
        return "候选买入"
    return "继续观察"


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
