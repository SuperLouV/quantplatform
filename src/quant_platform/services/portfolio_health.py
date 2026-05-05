"""Account health and risk report service."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from quant_platform.config import Settings
from quant_platform.indicators import IndicatorEngine
from quant_platform.risk import PortfolioRiskAnalyzer, RiskPolicy, load_risk_policy
from quant_platform.services.account import LongbridgeAccountService
from quant_platform.services.bootstrap import bootstrap_local_state
from quant_platform.services.market_events import MarketEventService
from quant_platform.services.operation_log import OperationLogger, operation_log_root
from quant_platform.services.yfinance_history import YFinanceHistoryUpdater


@dataclass(slots=True)
class AccountHealthRunResult:
    generated_at_beijing: str
    json_path: Path
    markdown_path: Path
    position_count: int
    health_score: int
    health_state: str
    warning_count: int


class AccountHealthService:
    """Generate account-aware concentration, loss, PDT, and event-risk reports."""

    def __init__(
        self,
        settings: Settings,
        *,
        account_service: LongbridgeAccountService | None = None,
        risk_policy: RiskPolicy | None = None,
    ) -> None:
        self.settings = settings
        self.artifacts = bootstrap_local_state(settings)
        self.account_service = account_service or LongbridgeAccountService(settings)
        policy_path = Path(__file__).resolve().parents[3] / "config" / "risk.example.yaml"
        self.risk_policy = risk_policy or load_risk_policy(policy_path)
        self.risk_analyzer = PortfolioRiskAnalyzer(self.risk_policy)
        self.market_events = MarketEventService(settings)
        self.history_updater = YFinanceHistoryUpdater(settings)
        self.indicator_engine = IndicatorEngine()
        self.logger = OperationLogger(operation_log_root(settings), "account_health")

    def generate(
        self,
        *,
        as_of: date | None = None,
        currency: str = "USD",
        day_trade_count_5d: int | None = None,
    ) -> AccountHealthRunResult:
        as_of = as_of or date.today()
        self.logger.info("account_health.generate.start", as_of=as_of.isoformat(), currency=currency)
        account = self.account_service.snapshot(currency=currency)
        snapshots, snapshot_notes = self._load_position_snapshots(
            [position.internal_symbol for position in account.positions],
            as_of=as_of,
        )
        events = self.market_events.load_events(start=as_of, end=as_of + timedelta(days=self.risk_policy.event_risk_window_days))
        assessment = self.risk_analyzer.assess(
            account,
            snapshots_by_symbol=snapshots,
            market_events=events,
            as_of=as_of,
            day_trade_count_5d=day_trade_count_5d,
        )
        payload = {
            "analysis_id": f"account_health:{datetime.now(tz=UTC).strftime('%Y%m%dT%H%M%SZ')}",
            "generated_at_beijing": assessment.generated_at_beijing,
            "timezone": "Asia/Shanghai",
            "as_of": as_of.isoformat(),
            "execution_boundary": "read_only_analysis_no_auto_order",
            "data_sources": {
                "account": account.provider,
                "snapshots": "local_processed_snapshots",
                "events": "local_market_events",
                "atr_history": "local_yfinance_bars_with_missing_history_backfill",
            },
            "risk_policy": self.risk_policy.to_dict(),
            "account": account.to_dict(),
            "risk_assessment": assessment.to_dict(),
            "single_stock_pl": _single_stock_pl(assessment.to_dict()["positions"]),
            "snapshot_notes": snapshot_notes,
            "position_actions": _position_actions(assessment.to_dict(), self.risk_policy),
            "improvement_plan": _improvement_plan(assessment.to_dict(), self.risk_policy),
        }
        json_path, markdown_path = self._write_outputs(payload)
        self.logger.info(
            "account_health.generate.success",
            json_path=str(json_path),
            markdown_path=str(markdown_path),
            position_count=assessment.position_count,
            health_score=assessment.health_score,
            warnings=len(assessment.warnings),
        )
        return AccountHealthRunResult(
            generated_at_beijing=assessment.generated_at_beijing,
            json_path=json_path,
            markdown_path=markdown_path,
            position_count=assessment.position_count,
            health_score=assessment.health_score,
            health_state=assessment.health_state,
            warning_count=len(assessment.warnings),
        )

    def _load_position_snapshots(self, symbols: list[str], *, as_of: date) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
        snapshots: dict[str, dict[str, Any]] = {}
        notes: list[dict[str, Any]] = []
        for symbol in symbols:
            path = self.artifacts.layout.stock_snapshot_path(symbol, "json")
            payload: dict[str, Any] = {"symbol": symbol}
            if not path.exists():
                notes.append({"symbol": symbol, "level": "warning", "message": "缺少本地 snapshot，报告将使用账户现价和行业兜底。"})
            else:
                try:
                    loaded = json.loads(path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    self.logger.error("account_health.snapshot.invalid_json", symbol=symbol, path=str(path))
                    notes.append({"symbol": symbol, "level": "warning", "message": "本地 snapshot JSON 损坏，已跳过该快照。"})
                else:
                    if isinstance(loaded, dict):
                        payload = loaded
            if not _has_atr(payload):
                note = self._enrich_missing_atr(symbol, payload, as_of=as_of)
                if note:
                    notes.append(note)
            snapshots[symbol] = payload
        return snapshots, notes

    def _enrich_missing_atr(self, symbol: str, snapshot: dict[str, Any], *, as_of: date) -> dict[str, Any] | None:
        bars_path = self.artifacts.layout.processed_symbol_path("yfinance", "bars", symbol)
        if not bars_path.exists():
            try:
                self.history_updater.update_symbol(symbol, end=as_of + timedelta(days=1))
            except Exception as exc:  # noqa: BLE001 - missing ATR is diagnostic; do not fail the whole account report.
                self.logger.error("account_health.atr_history.update_error", symbol=symbol, error=str(exc))
                return {"symbol": symbol, "level": "warning", "message": f"缺少本地日线且自动补拉失败：{exc}"}
        try:
            computation = self.indicator_engine.compute_from_parquet(bars_path)
        except Exception as exc:  # noqa: BLE001 - one symbol must not break account-level risk reporting.
            self.logger.error("account_health.atr_indicator.compute_error", symbol=symbol, path=str(bars_path), error=str(exc))
            return {"symbol": symbol, "level": "warning", "message": f"本地日线无法计算 ATR：{exc}"}

        indicators = snapshot.get("indicators") if isinstance(snapshot.get("indicators"), dict) else {}
        indicators = dict(indicators)
        indicators.update({key: value for key, value in computation.latest.items() if value is not None})
        snapshot["indicators"] = indicators
        snapshot["indicators_provider"] = "local_yfinance_bars"
        latest_date = _latest_indicator_date(computation.series)
        if latest_date:
            snapshot["latest_history_date_us"] = latest_date
        if _has_atr(snapshot):
            return {"symbol": symbol, "level": "info", "message": "缺失 ATR 已用本地/补拉日线即时计算。"}
        return {"symbol": symbol, "level": "warning", "message": "日线存在但 atr_14 仍为空，可能历史长度不足。"}

    def _write_outputs(self, payload: dict[str, Any]) -> tuple[Path, Path]:
        output_dir = self.settings.storage.processed_dir.parent / "reports" / "account_health"
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
        json_path = output_dir / f"account_health_{timestamp}.json"
        markdown_path = output_dir / f"account_health_{timestamp}.md"
        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        markdown_path.write_text(_render_markdown(payload), encoding="utf-8")
        return json_path, markdown_path


def _single_stock_pl(positions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "symbol": item.get("symbol"),
            "name": item.get("name"),
            "unrealized_pl": _round_optional(item.get("unrealized_pl")),
            "unrealized_pl_pct": _round_optional(item.get("unrealized_pl_pct")),
            "market_value": _round_optional(item.get("market_value")),
            "weight_pct": _round_optional(item.get("weight_pct")),
        }
        for item in positions
    ]


def _position_actions(assessment: dict[str, Any], policy: RiskPolicy) -> list[dict[str, Any]]:
    equity = _optional_float(assessment.get("equity")) or 0
    target_weight_pct = policy.max_position_weight * 100
    actions: list[dict[str, Any]] = []
    for item in assessment.get("positions") or []:
        if not isinstance(item, dict):
            continue
        weight_pct = _optional_float(item.get("weight_pct"))
        market_value = _optional_float(item.get("market_value"))
        current_price = _optional_float(item.get("current_price"))
        if weight_pct is None or market_value is None:
            continue
        target_value = equity * policy.max_position_weight if equity > 0 else None
        reduce_value = max(0.0, market_value - target_value) if target_value is not None else None
        reduce_shares = reduce_value / current_price if reduce_value is not None and current_price not in (None, 0) else None
        urgency = "观察"
        if item.get("concentration_status") == "breach" or item.get("max_loss_status") == "breach":
            urgency = "优先"
        elif weight_pct >= target_weight_pct * 0.8:
            urgency = "接近上限"
        action = "暂停加仓，等待下一次再平衡。"
        if reduce_value and reduce_value > 0:
            action = (
                f"将权重从 {weight_pct:.1f}% 降到 {target_weight_pct:.1f}% 左右，"
                f"约减少 ${reduce_value:,.0f}"
                + (f" / {reduce_shares:.1f} 股" if reduce_shares is not None else "")
                + "。"
            )
        actions.append(
            {
                "symbol": item.get("symbol"),
                "weight_pct": _round_optional(weight_pct),
                "target_weight_pct": round(target_weight_pct, 2),
                "reduce_value": _round_optional(reduce_value),
                "reduce_shares": _round_optional(reduce_shares),
                "urgency": urgency,
                "action": action,
            }
        )
    return sorted(actions, key=lambda item: (0 if item["urgency"] == "优先" else 1, -(item.get("weight_pct") or 0)))


def _improvement_plan(assessment: dict[str, Any], policy: RiskPolicy) -> list[str]:
    recommendations = [str(item) for item in assessment.get("recommendations") or []]
    warnings = assessment.get("warnings") or []
    actions = _position_actions(assessment, policy)
    if not warnings:
        return [*(item["action"] for item in actions if item.get("urgency") in {"优先", "接近上限"}), *recommendations]
    plan: list[str] = []
    priority_symbols = [str(item.get("symbol")) for item in actions if item.get("urgency") == "优先"]
    if priority_symbols:
        plan.append(f"减仓/控仓优先级：{', '.join(priority_symbols[:5])}；先处理单股超限或 ATR 风险超限的仓位。")
    for item in actions:
        if item.get("urgency") == "优先":
            plan.append(str(item.get("action")))
    if any("单股仓位" in str(item) for item in warnings):
        plan.append("先处理单股集中度：超限标的降到策略上限附近前，不再加仓同一标的。")
    if any("行业敞口" in str(item) for item in warnings):
        plan.append(
            f"行业敞口超限时，把对应行业权重压回 {policy.max_sector_weight * 100:.1f}% 以内；新增候选优先选择其它行业。"
        )
    if any("ATR" in str(item) or "亏损" in str(item) for item in warnings):
        plan.append("逐只确认 ATR 止损参考价和最大可承受亏损；止损只作为人工复盘参考。")
    if any("PDT" in str(item) for item in warnings):
        plan.append("低于 PDT 门槛时，避免日内反复开平；优先使用日线级别计划。")
    if any("事件风险" in str(item) for item in warnings):
        plan.append("财报、FOMC、CPI 等事件日前降低追涨和卖期权激进度。")
    return list(dict.fromkeys([*plan, *recommendations]))


def _render_markdown(payload: dict[str, Any]) -> str:
    risk = payload.get("risk_assessment", {})
    lines = [
        "# 账户健康度与风控报告",
        "",
        f"- 生成时间（北京）：{payload.get('generated_at_beijing')}",
        f"- 分析日期：{payload.get('as_of')}",
        "- 数据源：Longbridge 只读账户 / 本地快照 / 本地事件日历",
        "- 边界：只读分析，不自动下单、撤单或改单",
        "",
        "## 总览",
        "",
        f"- 健康度：{risk.get('health_state')}（{risk.get('health_score')} / 100）",
        f"- 账户权益：${_money(risk.get('equity'))}，现金比例：{_pct(risk.get('cash_ratio_pct'))}",
        f"- 持仓数量：{risk.get('position_count')}，组合 HHI：{risk.get('hhi')}",
        f"- PDT：{(risk.get('pdt') or {}).get('status')}，{(risk.get('pdt') or {}).get('message')}",
        "",
        "## 操作清单",
        "",
        "| 标的 | 当前权重 | 目标权重 | 建议减仓 | 优先级 | 动作 |",
        "| --- | ---: | ---: | ---: | --- | --- |",
    ]
    actions = payload.get("position_actions") or []
    if not actions:
        lines.append("| - | - | - | - | - | 暂无可量化控仓动作 |")
    for item in actions:
        reduce_value = _money(item.get("reduce_value"))
        reduce_shares = _optional_float(item.get("reduce_shares"))
        reduce_text = f"${reduce_value}" + (f" / {reduce_shares:.1f} 股" if reduce_shares else "")
        lines.append(
            "| {symbol} | {weight} | {target} | {reduce} | {urgency} | {action} |".format(
                symbol=item.get("symbol"),
                weight=_pct(item.get("weight_pct")),
                target=_pct(item.get("target_weight_pct")),
                reduce=reduce_text if item.get("reduce_value") else "-",
                urgency=item.get("urgency"),
                action=str(item.get("action") or "-").replace("|", "/"),
            )
        )
    lines.extend(
        [
        "",
        "## 单股集中度与止损",
        "",
        "| 标的 | 行业 | 权重 | 成本盈亏 | ATR止损 | ATR风险/权益 | 风险提示 |",
        "| --- | --- | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for item in risk.get("positions") or []:
        stop = item.get("atr_stop") or {}
        lines.append(
            "| {symbol} | {sector} | {weight} | {pl} | {stop_price} | {atr_loss} | {flags} |".format(
                symbol=item.get("symbol"),
                sector=item.get("sector"),
                weight=_pct(item.get("weight_pct")),
                pl=_pct(item.get("unrealized_pl_pct")),
                stop_price=_money(stop.get("stop_price")),
                atr_loss=_pct(stop.get("estimated_loss_pct_of_equity")),
                flags="；".join(item.get("flags") or stop.get("notes") or []) or "-",
            )
        )
    lines.extend(["", "## 行业敞口", "", "| 行业 | 权重 | 市值 | 标的 | 状态 |", "| --- | ---: | ---: | --- | --- |"])
    for item in risk.get("sector_exposures") or []:
        lines.append(
            "| {sector} | {weight} | {value} | {symbols} | {status} |".format(
                sector=item.get("sector"),
                weight=_pct(item.get("weight_pct")),
                value=_money(item.get("market_value")),
                symbols=", ".join(item.get("symbols") or []),
                status=item.get("status"),
            )
        )
    lines.extend(["", "## 事件风险", "", "| 日期 | 类型 | 标的 | 重要性 | 事件 |", "| --- | --- | --- | --- | --- |"])
    events = risk.get("event_risks") or []
    if not events:
        lines.append("| - | - | - | - | 未来窗口内暂无高/中重要性事件风险 |")
    for event in events:
        lines.append(
            "| {date} | {type} | {symbol} | {importance} | {title} |".format(
                date=event.get("event_date") or "-",
                type=event.get("event_type"),
                symbol=event.get("symbol") or "全市场",
                importance=event.get("importance"),
                title=str(event.get("title") or "-").replace("|", "/"),
            )
        )
    lines.extend(["", "## 改善建议", ""])
    for item in payload.get("improvement_plan") or []:
        lines.append(f"- {item}")
    if payload.get("snapshot_notes"):
        lines.extend(["", "## 数据补齐记录", ""])
        for item in payload.get("snapshot_notes") or []:
            lines.append(f"- {item.get('symbol')}: {item.get('message')}")
    if risk.get("warnings"):
        lines.extend(["", "## 风险提示", ""])
        for item in risk.get("warnings") or []:
            lines.append(f"- {item}")
    return "\n".join(lines).rstrip() + "\n"


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


def _optional_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _round_optional(value: Any) -> float | None:
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def _has_atr(snapshot: dict[str, Any]) -> bool:
    indicators = snapshot.get("indicators") if isinstance(snapshot.get("indicators"), dict) else {}
    try:
        return float(indicators.get("atr_14")) > 0
    except (TypeError, ValueError):
        return False


def _latest_indicator_date(frame: pd.DataFrame) -> str | None:
    if frame.empty or "timestamp" not in frame:
        return None
    try:
        return pd.to_datetime(frame["timestamp"], utc=True).max().date().isoformat()
    except Exception:  # noqa: BLE001 - diagnostic only.
        return None
