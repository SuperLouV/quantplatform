"""Strategy analysis for real Longbridge positions and watchlists."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from quant_platform.clients import LongbridgeCLIClient
from quant_platform.config import Settings
from quant_platform.indicators import IndicatorEngine
from quant_platform.indicators.signals import SignalDetector
from quant_platform.screeners import MarketScanner
from quant_platform.services.bootstrap import bootstrap_local_state
from quant_platform.services.longbridge_pools import LongbridgeStockPoolService
from quant_platform.services.operation_log import OperationLogger, operation_log_root
from quant_platform.services.yfinance_history import YFinanceHistoryUpdater
from quant_platform.time_utils import iso_beijing


@dataclass(slots=True)
class PortfolioStrategyResult:
    generated_at_beijing: str
    json_path: Path
    markdown_path: Path
    position_count: int
    watchlist_count: int
    combined_count: int
    quote_success_count: int
    quote_error_count: int
    history_error_count: int


class PortfolioStrategyService:
    """Analyze real holdings and watchlist names without producing orders."""

    def __init__(self, settings: Settings, client: LongbridgeCLIClient | None = None) -> None:
        self.settings = settings
        self.artifacts = bootstrap_local_state(settings)
        self.client = client or LongbridgeCLIClient.from_data_config(settings.data)
        self.pool_service = LongbridgeStockPoolService(settings, client=self.client)
        self.indicator_engine = IndicatorEngine()
        self.signal_detector = SignalDetector()
        self.market_scanner = MarketScanner()
        self.history_updater = YFinanceHistoryUpdater(settings)
        self.logger = OperationLogger(operation_log_root(settings), "portfolio_strategy")

    def analyze(self, *, update_history: bool = False) -> PortfolioStrategyResult:
        self.logger.info("portfolio_strategy.analyze.start", update_history=update_history)
        sync_result = self.pool_service.sync()
        metadata = json.loads(sync_result.metadata_path.read_text(encoding="utf-8"))
        combined = metadata.get("combined") if isinstance(metadata.get("combined"), dict) else {}
        positions = metadata.get("positions") if isinstance(metadata.get("positions"), dict) else {}
        watchlist = metadata.get("watchlist") if isinstance(metadata.get("watchlist"), dict) else {}
        symbols = list(combined.keys()) if isinstance(combined, dict) else []

        symbol_contexts: list[dict[str, Any]] = []
        for symbol in symbols:
            context = self._symbol_context(symbol, update_history=update_history)
            context["metadata"] = combined.get(symbol, {}) if isinstance(combined, dict) else {}
            symbol_contexts.append(context)

        scanner_input = [context["snapshot"] for context in symbol_contexts]
        scan_result = self.market_scanner.scan_snapshots(scanner_input)
        scan_by_symbol = {candidate.symbol: candidate for candidate in scan_result.candidates}

        position_items = [
            self._position_health(symbol, meta, _context_by_symbol(symbol_contexts, symbol), scan_by_symbol.get(symbol))
            for symbol, meta in positions.items()
            if isinstance(meta, dict)
        ]
        watchlist_items = [
            self._watchlist_attention(symbol, meta, _context_by_symbol(symbol_contexts, symbol), scan_by_symbol.get(symbol))
            for symbol, meta in watchlist.items()
            if isinstance(meta, dict)
        ]
        position_items = sorted(position_items, key=lambda item: (item.get("health_score") is None, -(item.get("health_score") or 0), item["symbol"]))
        watchlist_items = sorted(watchlist_items, key=lambda item: (item.get("attention_score") is None, -(item.get("attention_score") or 0), item["symbol"]))

        payload = {
            "generated_at_beijing": iso_beijing(),
            "timezone": "Asia/Shanghai",
            "analysis_id": "longbridge_real_portfolio_basic_v1",
            "quote_provider": "longbridge_cli",
            "history_provider": "yfinance",
            "execution_boundary": "read_only_analysis_no_auto_order",
            "pool_sync": {
                "metadata_path": str(sync_result.metadata_path),
                "pool_paths": {key: str(path) for key, path in sync_result.pool_paths.items()},
                "position_count": sync_result.position_count,
                "watchlist_count": sync_result.watchlist_count,
                "combined_count": sync_result.combined_count,
                "excluded_count": sync_result.excluded_count,
            },
            "summary": {
                "positions": _summarize_states(position_items, "health_state"),
                "watchlist": _summarize_states(watchlist_items, "attention_state"),
                "quote_success_count": sum(1 for item in symbol_contexts if item.get("quote_status") == "success"),
                "quote_error_count": sum(1 for item in symbol_contexts if item.get("quote_status") == "error"),
                "history_error_count": sum(1 for item in symbol_contexts if item.get("history_status") == "error"),
            },
            "positions": position_items,
            "watchlist": watchlist_items,
            "symbol_diagnostics": [
                {
                    "symbol": context["symbol"],
                    "quote_status": context["quote_status"],
                    "history_status": context["history_status"],
                    "data_quality": context["snapshot"].get("data_quality"),
                    "errors": context["errors"],
                }
                for context in symbol_contexts
            ],
        }
        json_path, markdown_path = self._write_outputs(payload)
        self.logger.info(
            "portfolio_strategy.analyze.success",
            json_path=str(json_path),
            markdown_path=str(markdown_path),
            positions=len(position_items),
            watchlist=len(watchlist_items),
        )
        return PortfolioStrategyResult(
            generated_at_beijing=str(payload["generated_at_beijing"]),
            json_path=json_path,
            markdown_path=markdown_path,
            position_count=len(position_items),
            watchlist_count=len(watchlist_items),
            combined_count=len(symbol_contexts),
            quote_success_count=int(payload["summary"]["quote_success_count"]),
            quote_error_count=int(payload["summary"]["quote_error_count"]),
            history_error_count=int(payload["summary"]["history_error_count"]),
        )

    def _symbol_context(self, symbol: str, *, update_history: bool) -> dict[str, Any]:
        errors: list[str] = []
        quote: dict[str, Any] = {"symbol": symbol}
        quote_status = "missing"
        try:
            quote = self.client.fetch_quote_snapshot(symbol)
            quote_status = "success"
        except Exception as exc:  # noqa: BLE001 - one symbol must not break the real-pool report.
            quote_status = "error"
            errors.append(f"longbridge_quote_error:{exc}")
            self.logger.error("portfolio_strategy.quote.error", symbol=symbol, error=str(exc))

        history_status = "missing"
        if update_history:
            try:
                self.history_updater.update_symbol(symbol)
            except Exception as exc:  # noqa: BLE001 - report should still show missing history.
                errors.append(f"yfinance_history_update_error:{exc}")
                self.logger.error("portfolio_strategy.history_update.error", symbol=symbol, error=str(exc))

        indicators: dict[str, Any] = {}
        signal_summary = None
        path = self.artifacts.layout.processed_symbol_path("yfinance", "bars", symbol)
        latest_bar = {}
        if path.exists():
            try:
                computation = self.indicator_engine.compute_from_parquet(path)
                indicators = computation.latest
                signal_summary = self.signal_detector.detect(symbol, computation.series)
                latest_bar = _latest_bar(computation.series)
                history_status = "success"
            except Exception as exc:  # noqa: BLE001 - malformed local history is a per-symbol diagnostic.
                history_status = "error"
                errors.append(f"yfinance_history_read_error:{exc}")
                self.logger.error("portfolio_strategy.history_read.error", symbol=symbol, path=str(path), error=str(exc))
        else:
            errors.append("missing_yfinance_bars")

        snapshot = _scanner_snapshot(symbol, quote=quote, latest_bar=latest_bar, indicators=indicators, errors=errors)
        return {
            "symbol": symbol,
            "quote": quote,
            "quote_status": quote_status,
            "history_status": history_status,
            "snapshot": snapshot,
            "signal_summary": signal_summary,
            "errors": errors,
        }

    def _position_health(
        self,
        symbol: str,
        meta: dict[str, Any],
        context: dict[str, Any],
        scan_candidate: object | None,
    ) -> dict[str, Any]:
        scan = _scan_payload(scan_candidate)
        signal_summary = _signal_summary_payload(context.get("signal_summary"))
        price = _optional_float(context["snapshot"].get("current_price") or context["snapshot"].get("latest_close"))
        quantity = _optional_float(meta.get("quantity"))
        cost_price = _optional_float(meta.get("cost_price"))
        pnl_pct = ((price - cost_price) / cost_price) * 100 if price is not None and cost_price not in (None, 0) else None
        market_value = price * quantity if price is not None and quantity is not None else None
        risk_flags = _risk_flags(context, scan, signal_summary, pnl_pct=pnl_pct, cost_price=cost_price)
        score = _bounded_score(
            (scan.get("score") or 30)
            + min(signal_summary["net_score"] * 2, 12)
            - min(signal_summary["short_score"] * 3, 24)
            + _pnl_score_adjustment(pnl_pct)
            - (15 if risk_flags else 0)
        )
        state = _health_state(score, context["snapshot"].get("data_quality"), scan.get("risk_level"))
        return {
            "symbol": symbol,
            "name": meta.get("name"),
            "quantity": quantity,
            "cost_price": cost_price,
            "current_price": price,
            "market_value": market_value,
            "unrealized_pl_pct": _round(pnl_pct),
            "health_score": score,
            "health_state": state,
            "manual_review": _manual_position_review(state),
            "risk_flags": risk_flags,
            "scanner": scan,
            "signals": signal_summary,
            "data": _data_payload(context),
        }

    def _watchlist_attention(
        self,
        symbol: str,
        meta: dict[str, Any],
        context: dict[str, Any],
        scan_candidate: object | None,
    ) -> dict[str, Any]:
        scan = _scan_payload(scan_candidate)
        signal_summary = _signal_summary_payload(context.get("signal_summary"))
        attention_score = _bounded_score(
            (scan.get("score") or 30)
            + min(signal_summary["long_score"] * 3, 18)
            - min(signal_summary["short_score"] * 2, 18)
            + (8 if scan.get("action") == "候选买入" else 0)
        )
        state = _attention_state(attention_score, context["snapshot"].get("data_quality"), scan.get("risk_level"))
        return {
            "symbol": symbol,
            "name": meta.get("name"),
            "watchlist_groups": meta.get("watchlist_groups") or [],
            "current_price": _optional_float(context["snapshot"].get("current_price") or context["snapshot"].get("latest_close")),
            "attention_score": attention_score,
            "attention_state": state,
            "manual_review": _manual_watchlist_review(state),
            "scanner": scan,
            "signals": signal_summary,
            "data": _data_payload(context),
        }

    def _write_outputs(self, payload: dict[str, Any]) -> tuple[Path, Path]:
        output_dir = self.settings.storage.processed_dir.parent / "reports" / "portfolio_strategy"
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
        json_path = output_dir / f"longbridge_portfolio_strategy_{timestamp}.json"
        markdown_path = output_dir / f"longbridge_portfolio_strategy_{timestamp}.md"
        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8")
        markdown_path.write_text(_render_markdown(payload), encoding="utf-8")
        return json_path, markdown_path


def _scanner_snapshot(
    symbol: str,
    *,
    quote: dict[str, Any],
    latest_bar: dict[str, Any],
    indicators: dict[str, Any],
    errors: list[str],
) -> dict[str, Any]:
    latest_close = _optional_float(quote.get("latest_close") or latest_bar.get("close"))
    previous_close = _optional_float(quote.get("previous_close") or latest_bar.get("previous_close"))
    current_price = _optional_float(quote.get("current_price") or latest_close)
    change_percent = _optional_float(quote.get("change_percent"))
    if change_percent is None and current_price is not None and previous_close not in (None, 0):
        change_percent = ((current_price - previous_close) / previous_close) * 100
    return {
        "symbol": symbol,
        "company_name": quote.get("company_name"),
        "current_price": current_price,
        "latest_close": latest_close,
        "previous_close": previous_close,
        "change_percent": change_percent,
        "latest_volume": _optional_float(quote.get("latest_volume") or latest_bar.get("volume")),
        "latest_history_date_us": quote.get("latest_history_date_us") or latest_bar.get("date"),
        "snapshot_refreshed_at_beijing": quote.get("snapshot_refreshed_at_beijing") or iso_beijing(),
        "quote_provider": quote.get("quote_provider") or quote.get("provider") or "longbridge_cli",
        "quote_provider_status": quote.get("quote_provider_status") or ("error" if errors else "success"),
        "indicators": indicators,
        "screening_reasons": errors,
        "data_quality": "正常" if indicators and not errors else ("指标不足" if not indicators else "数据警告"),
    }


def _latest_bar(frame: pd.DataFrame) -> dict[str, Any]:
    if frame.empty:
        return {}
    current = frame.iloc[-1]
    previous = frame.iloc[-2] if len(frame.index) > 1 else None
    timestamp = pd.Timestamp(current["timestamp"]) if "timestamp" in current else None
    return {
        "date": timestamp.date().isoformat() if timestamp is not None else None,
        "close": _optional_float(current.get("close")),
        "volume": _optional_float(current.get("volume")),
        "previous_close": _optional_float(previous.get("close")) if previous is not None else None,
    }


def _scan_payload(candidate: object | None) -> dict[str, Any]:
    if candidate is None:
        return {"score": None, "action": "数据不足", "risk_level": "高", "data_quality": "指标不足", "signals": []}
    payload = asdict(candidate)
    return {
        "score": payload.get("score"),
        "action": payload.get("action"),
        "risk_level": payload.get("risk_level"),
        "trend_state": payload.get("trend_state"),
        "rsi_state": payload.get("rsi_state"),
        "macd_state": payload.get("macd_state"),
        "volume_state": payload.get("volume_state"),
        "data_quality": payload.get("data_quality"),
        "momentum_rank_pct": payload.get("momentum_rank_pct"),
        "signals": payload.get("signals", []),
    }


def _signal_summary_payload(summary: object | None) -> dict[str, Any]:
    if summary is None:
        return {"as_of": None, "long_score": 0, "short_score": 0, "net_score": 0, "signals": []}
    payload = asdict(summary)
    return {
        "as_of": _json_default(payload.get("as_of")),
        "long_score": payload.get("long_score", 0),
        "short_score": payload.get("short_score", 0),
        "net_score": payload.get("net_score", 0),
        "signals": payload.get("signals", []),
    }


def _risk_flags(
    context: dict[str, Any],
    scan: dict[str, Any],
    signal_summary: dict[str, Any],
    *,
    pnl_pct: float | None,
    cost_price: float | None,
) -> list[str]:
    flags: list[str] = []
    if context.get("quote_status") != "success":
        flags.append("Longbridge 实时行情失败，需手工确认价格。")
    if context.get("history_status") != "success":
        flags.append("本地 yfinance 日线历史缺失或不可读。")
    if scan.get("risk_level") == "高":
        flags.append("Scanner 风险等级为高。")
    if signal_summary.get("short_score", 0) > 0:
        flags.append("近期触发偏空技术信号。")
    if cost_price is None:
        flags.append("缺少成本价，无法计算持仓盈亏健康度。")
    if pnl_pct is not None and pnl_pct <= -8:
        flags.append("相对成本回撤超过 8%，需要人工复核止损或仓位。")
    return flags


def _data_payload(context: dict[str, Any]) -> dict[str, Any]:
    snapshot = context["snapshot"]
    return {
        "quote_status": context.get("quote_status"),
        "history_status": context.get("history_status"),
        "latest_history_date_us": snapshot.get("latest_history_date_us"),
        "snapshot_refreshed_at_beijing": snapshot.get("snapshot_refreshed_at_beijing"),
        "errors": context.get("errors", []),
    }


def _pnl_score_adjustment(pnl_pct: float | None) -> int:
    if pnl_pct is None:
        return -5
    if pnl_pct <= -12:
        return -18
    if pnl_pct <= -6:
        return -10
    if pnl_pct >= 15:
        return 6
    if pnl_pct >= 5:
        return 3
    return 0


def _health_state(score: int | None, data_quality: object, risk_level: object) -> str:
    if data_quality != "正常":
        return "数据不足"
    if risk_level == "高" or (score or 0) < 45:
        return "风险复核"
    if (score or 0) >= 70:
        return "健康"
    return "观察"


def _attention_state(score: int | None, data_quality: object, risk_level: object) -> str:
    if data_quality != "正常":
        return "数据不足"
    if risk_level == "高" or (score or 0) < 45:
        return "暂缓"
    if (score or 0) >= 72:
        return "重点关注"
    return "继续观察"


def _manual_position_review(state: str) -> str:
    if state == "健康":
        return "持仓状态相对健康，保留人工复盘。"
    if state == "观察":
        return "继续观察，重点确认趋势和事件风险。"
    if state == "风险复核":
        return "进入人工风险复核，不生成自动卖出动作。"
    return "数据不足，先确认行情和历史数据。"


def _manual_watchlist_review(state: str) -> str:
    if state == "重点关注":
        return "可加入人工重点观察清单，等待交易计划确认。"
    if state == "继续观察":
        return "保持观察，等待更强趋势或量能确认。"
    if state == "暂缓":
        return "暂缓推进，优先看风险或趋势修复。"
    return "数据不足，先补齐日线历史和实时行情。"


def _render_markdown(payload: dict[str, Any]) -> str:
    summary = payload.get("summary", {})
    lines = [
        "# Longbridge 真实持仓与自选策略摘要",
        "",
        f"- 生成时间（北京）：{payload.get('generated_at_beijing')}",
        "- 数据源：Longbridge CLI 实时行情 / yfinance 本地日线历史",
        "- 边界：只读分析，不自动下单、撤单或改单",
        "",
        "## 总览",
        "",
        f"- 持仓视角：{summary.get('positions')}",
        f"- 自选视角：{summary.get('watchlist')}",
        f"- Longbridge 行情成功/失败：{summary.get('quote_success_count')} / {summary.get('quote_error_count')}",
        f"- yfinance 历史异常：{summary.get('history_error_count')}",
        "",
        "## 持仓健康度",
        "",
        "| 标的 | 状态 | 分数 | 成本盈亏% | Scanner | 风险提示 |",
        "| --- | --- | ---: | ---: | --- | --- |",
    ]
    for item in payload.get("positions", []):
        lines.append(
            "| {symbol} | {state} | {score} | {pnl} | {action} | {flags} |".format(
                symbol=item.get("symbol"),
                state=item.get("health_state"),
                score=item.get("health_score"),
                pnl=_display(item.get("unrealized_pl_pct")),
                action=(item.get("scanner") or {}).get("action"),
                flags="；".join(item.get("risk_flags") or []) or "-",
            )
        )
    lines.extend(["", "## 自选关注度", "", "| 标的 | 分组 | 状态 | 分数 | Scanner |", "| --- | --- | --- | ---: | --- |"])
    for item in payload.get("watchlist", []):
        lines.append(
            "| {symbol} | {groups} | {state} | {score} | {action} |".format(
                symbol=item.get("symbol"),
                groups=" / ".join(item.get("watchlist_groups") or []) or "-",
                state=item.get("attention_state"),
                score=item.get("attention_score"),
                action=(item.get("scanner") or {}).get("action"),
            )
        )
    lines.extend(
        [
            "",
            "## 复核提示",
            "",
            "- Scanner 输出是候选优先级，不是买卖指令。",
            "- 持仓健康度结合成本、实时价、日线指标和规则信号，只用于人工风险复核。",
            "- 自选关注度用于决定明天重点看哪些股票，不代表入场信号。",
        ]
    )
    return "\n".join(lines) + "\n"


def _summarize_states(items: list[dict[str, Any]], key: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for item in items:
        state = str(item.get(key) or "未知")
        result[state] = result.get(state, 0) + 1
    return result


def _context_by_symbol(contexts: list[dict[str, Any]], symbol: str) -> dict[str, Any]:
    return next(context for context in contexts if context["symbol"] == symbol)


def _bounded_score(value: float | int | None) -> int | None:
    if value is None:
        return None
    return round(max(0, min(100, float(value))))


def _optional_float(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(result):
        return None
    return result


def _round(value: float | None, digits: int = 2) -> float | None:
    return round(value, digits) if value is not None else None


def _display(value: object) -> str:
    return "-" if value is None else str(value)


def _json_default(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    return value
