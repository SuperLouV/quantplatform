"""Historical execution review from read-only broker records."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from quant_platform.clients import LongbridgeCLIClient
from quant_platform.config import Settings
from quant_platform.services.bootstrap import bootstrap_local_state
from quant_platform.services.operation_log import OperationLogger, operation_log_root
from quant_platform.time_utils import iso_beijing


@dataclass(slots=True)
class TradeReviewRunResult:
    generated_at_beijing: str
    json_path: Path
    markdown_path: Path
    execution_count: int
    closed_trade_count: int
    error_count: int


class TradeReviewService:
    """Build a deterministic long-only trade review from execution fills."""

    def __init__(self, settings: Settings, client: LongbridgeCLIClient | None = None) -> None:
        self.settings = settings
        self.artifacts = bootstrap_local_state(settings)
        self.client = client or LongbridgeCLIClient.from_data_config(settings.data)
        self.logger = OperationLogger(operation_log_root(settings), "trade_review")

    def generate(self, *, start: date | None = None, end: date | None = None) -> TradeReviewRunResult:
        self.logger.info(
            "trade_review.generate.start",
            start=start.isoformat() if start else None,
            end=end.isoformat() if end else None,
        )
        errors: list[dict[str, str]] = []
        orders: list[dict[str, Any]] = []
        executions: list[dict[str, Any]] = []
        try:
            orders = self.client.fetch_history_orders(start=start, end=end)
        except Exception as exc:  # noqa: BLE001 - orders are secondary context for the review.
            errors.append({"source": "orders", "error": str(exc)})
            self.logger.error("trade_review.orders.error", error=str(exc))
        try:
            executions = self.client.fetch_history_executions(start=start, end=end)
        except Exception as exc:  # noqa: BLE001 - write an error report instead of hiding the failure.
            errors.append({"source": "executions", "error": str(exc)})
            self.logger.error("trade_review.executions.error", error=str(exc))

        normalized = [_normalize_execution(item) for item in executions]
        normalized = [item for item in normalized if item is not None]
        closed_trades, open_lots, ignored = _match_long_trades(normalized)
        metrics = _review_metrics(closed_trades)
        payload = {
            "analysis_id": f"trade_review:{datetime.now(tz=UTC).strftime('%Y%m%dT%H%M%SZ')}",
            "generated_at_beijing": iso_beijing(),
            "timezone": "Asia/Shanghai",
            "window": {"start": start.isoformat() if start else None, "end": end.isoformat() if end else None},
            "execution_boundary": "read_only_analysis_no_auto_order",
            "data_sources": {"orders": "longbridge_cli", "executions": "longbridge_cli"},
            "summary": {
                **metrics,
                "order_count": len(orders),
                "execution_count": len(normalized),
                "closed_trade_count": len(closed_trades),
                "open_lot_count": sum(len(lots) for lots in open_lots.values()),
                "ignored_execution_count": len(ignored),
                "error_count": len(errors),
            },
            "by_symbol": _group_stats(closed_trades, key="symbol"),
            "by_month": _group_stats(closed_trades, key="month"),
            "closed_trades": closed_trades,
            "open_lots": {symbol: lots for symbol, lots in open_lots.items() if lots},
            "ignored_executions": ignored,
            "errors": errors,
            "notes": [
                "第一版复盘按普通股票多头 FIFO 成本匹配成交记录。",
                "期权、做空、转仓和公司行动暂不进入胜率/盈亏比统计。",
            ],
        }
        json_path, markdown_path = self._write_outputs(payload)
        self.logger.info(
            "trade_review.generate.success",
            json_path=str(json_path),
            markdown_path=str(markdown_path),
            executions=len(normalized),
            closed_trades=len(closed_trades),
            errors=len(errors),
        )
        return TradeReviewRunResult(
            generated_at_beijing=str(payload["generated_at_beijing"]),
            json_path=json_path,
            markdown_path=markdown_path,
            execution_count=len(normalized),
            closed_trade_count=len(closed_trades),
            error_count=len(errors),
        )

    def _write_outputs(self, payload: dict[str, Any]) -> tuple[Path, Path]:
        output_dir = self.settings.storage.processed_dir.parent / "reports" / "trade_review"
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
        json_path = output_dir / f"trade_review_{timestamp}.json"
        markdown_path = output_dir / f"trade_review_{timestamp}.md"
        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        markdown_path.write_text(_render_markdown(payload), encoding="utf-8")
        return json_path, markdown_path


def _normalize_execution(raw: dict[str, Any]) -> dict[str, Any] | None:
    symbol = _symbol(raw.get("symbol") or raw.get("stock_symbol") or raw.get("instrument_symbol"))
    side = _side(raw.get("side") or raw.get("direction") or raw.get("trade_side"))
    quantity = _float(raw.get("quantity") or raw.get("qty") or raw.get("executed_quantity") or raw.get("filled_quantity"))
    price = _float(raw.get("price") or raw.get("executed_price") or raw.get("avg_price") or raw.get("filled_price"))
    timestamp = _timestamp(raw.get("executed_at") or raw.get("trade_time") or raw.get("updated_at") or raw.get("created_at"))
    if not symbol or side not in {"BUY", "SELL"} or quantity is None or quantity <= 0 or price is None or timestamp is None:
        return None
    return {
        "symbol": symbol,
        "side": side,
        "quantity": quantity,
        "price": price,
        "amount": quantity * price,
        "timestamp": timestamp.isoformat(),
        "date": timestamp.date().isoformat(),
        "month": timestamp.strftime("%Y-%m"),
        "raw": raw,
    }


def _match_long_trades(executions: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    lots: dict[str, list[dict[str, Any]]] = {}
    closed: list[dict[str, Any]] = []
    ignored: list[dict[str, Any]] = []
    for execution in sorted(executions, key=lambda item: item["timestamp"]):
        symbol = execution["symbol"]
        if execution["side"] == "BUY":
            lots.setdefault(symbol, []).append(
                {
                    "symbol": symbol,
                    "quantity": execution["quantity"],
                    "remaining_quantity": execution["quantity"],
                    "price": execution["price"],
                    "timestamp": execution["timestamp"],
                    "date": execution["date"],
                }
            )
            continue
        remaining_sell = execution["quantity"]
        symbol_lots = lots.setdefault(symbol, [])
        while remaining_sell > 1e-9 and symbol_lots:
            lot = symbol_lots[0]
            matched_qty = min(remaining_sell, lot["remaining_quantity"])
            buy_price = lot["price"]
            sell_price = execution["price"]
            buy_time = datetime.fromisoformat(lot["timestamp"])
            sell_time = datetime.fromisoformat(execution["timestamp"])
            pnl = (sell_price - buy_price) * matched_qty
            closed.append(
                {
                    "symbol": symbol,
                    "quantity": round(matched_qty, 6),
                    "buy_date": lot["date"],
                    "sell_date": execution["date"],
                    "month": execution["month"],
                    "buy_price": round(buy_price, 4),
                    "sell_price": round(sell_price, 4),
                    "gross_pnl": round(pnl, 2),
                    "return_pct": round((sell_price - buy_price) / buy_price * 100, 2) if buy_price else None,
                    "holding_days": max(0, (sell_time.date() - buy_time.date()).days),
                    "outcome": "win" if pnl > 0 else "loss" if pnl < 0 else "flat",
                }
            )
            lot["remaining_quantity"] -= matched_qty
            remaining_sell -= matched_qty
            if lot["remaining_quantity"] <= 1e-9:
                symbol_lots.pop(0)
        if remaining_sell > 1e-9:
            ignored.append({**execution, "reason": "sell_without_matching_long_lot", "unmatched_quantity": round(remaining_sell, 6)})
    return closed, lots, ignored


def _review_metrics(trades: list[dict[str, Any]]) -> dict[str, Any]:
    if not trades:
        return {
            "win_rate_pct": None,
            "profit_factor": None,
            "average_win": None,
            "average_loss": None,
            "average_holding_days": None,
            "max_drawdown": 0.0,
            "total_realized_pnl": 0.0,
        }
    wins = [float(item["gross_pnl"]) for item in trades if float(item["gross_pnl"]) > 0]
    losses = [float(item["gross_pnl"]) for item in trades if float(item["gross_pnl"]) < 0]
    total_pnl = sum(float(item["gross_pnl"]) for item in trades)
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    return {
        "win_rate_pct": round(len(wins) / len(trades) * 100, 2),
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss > 0 else None,
        "average_win": round(gross_win / len(wins), 2) if wins else None,
        "average_loss": round(sum(losses) / len(losses), 2) if losses else None,
        "average_holding_days": round(sum(float(item["holding_days"]) for item in trades) / len(trades), 2),
        "max_drawdown": round(_max_drawdown([float(item["gross_pnl"]) for item in trades]), 2),
        "total_realized_pnl": round(total_pnl, 2),
    }


def _group_stats(trades: list[dict[str, Any]], *, key: str) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for trade in trades:
        grouped.setdefault(str(trade.get(key) or "unknown"), []).append(trade)
    return {name: {"trade_count": len(items), **_review_metrics(items)} for name, items in sorted(grouped.items())}


def _max_drawdown(pnls: list[float]) -> float:
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        max_dd = min(max_dd, equity - peak)
    return max_dd


def _render_markdown(payload: dict[str, Any]) -> str:
    summary = payload.get("summary", {})
    lines = [
        "# 历史交易记录复盘",
        "",
        f"- 生成时间（北京）：{payload.get('generated_at_beijing')}",
        f"- 窗口：{(payload.get('window') or {}).get('start') or '-'} 至 {(payload.get('window') or {}).get('end') or '-'}",
        "- 数据源：Longbridge CLI 只读订单/成交记录",
        "- 边界：只读复盘，不自动下单、撤单或改单",
        "",
        "## 总览",
        "",
        f"- 成交记录：{summary.get('execution_count')}，已闭合交易：{summary.get('closed_trade_count')}",
        f"- 胜率：{_pct(summary.get('win_rate_pct'))}，盈亏比：{summary.get('profit_factor') or '-'}",
        f"- 平均持有：{summary.get('average_holding_days') or '-'} 天，最大回撤：${_money(summary.get('max_drawdown'))}",
        f"- 已实现盈亏：${_money(summary.get('total_realized_pnl'))}",
        "",
        "## 按个股统计",
        "",
        "| 标的 | 笔数 | 胜率 | 盈亏比 | 已实现盈亏 | 平均持有 |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for symbol, stats in (payload.get("by_symbol") or {}).items():
        lines.append(
            f"| {symbol} | {stats.get('trade_count')} | {_pct(stats.get('win_rate_pct'))} | {stats.get('profit_factor') or '-'} | "
            f"{_money(stats.get('total_realized_pnl'))} | {stats.get('average_holding_days') or '-'} |"
        )
    lines.extend(["", "## 按月份统计", "", "| 月份 | 笔数 | 胜率 | 盈亏比 | 已实现盈亏 |", "| --- | ---: | ---: | ---: | ---: |"])
    for month, stats in (payload.get("by_month") or {}).items():
        lines.append(
            f"| {month} | {stats.get('trade_count')} | {_pct(stats.get('win_rate_pct'))} | {stats.get('profit_factor') or '-'} | "
            f"{_money(stats.get('total_realized_pnl'))} |"
        )
    if payload.get("errors"):
        lines.extend(["", "## 数据异常", ""])
        for error in payload.get("errors") or []:
            lines.append(f"- {error.get('source')}: {error.get('error')}")
    lines.extend(["", "## 口径说明", ""])
    for note in payload.get("notes") or []:
        lines.append(f"- {note}")
    return "\n".join(lines).rstrip() + "\n"


def _symbol(value: Any) -> str:
    return str(value or "").split(".", 1)[0].upper()


def _side(value: Any) -> str:
    text = str(value or "").upper()
    if text in {"BUY", "B", "BOT"} or "BUY" in text:
        return "BUY"
    if text in {"SELL", "S", "SLD"} or "SELL" in text:
        return "SELL"
    return text


def _float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _timestamp(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _money(value: Any) -> str:
    try:
        return f"{float(value):,.2f}"
    except (TypeError, ValueError):
        return "-"


def _pct(value: Any) -> str:
    try:
        return f"{float(value):.2f}%"
    except (TypeError, ValueError):
        return "-"
