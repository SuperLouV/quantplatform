"""Generate a Chinese daily market report from local artifacts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from quant_platform.config import Settings
from quant_platform.services.bootstrap import bootstrap_local_state
from quant_platform.services.market_events import MarketEventService
from quant_platform.services.market_overview import MarketOverview, MarketOverviewService
from quant_platform.services.operation_log import OperationLogger, operation_log_root
from quant_platform.services.ui_data import UIDataService
from quant_platform.time_utils import iso_beijing, latest_completed_us_market_date, now_beijing, to_beijing


@dataclass(slots=True)
class DailyReportResult:
    pool_id: str
    market_date_us: date
    generated_at_beijing: str
    path: Path
    scanner_count: int
    market_events_count: int


class DailyReportService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.artifacts = bootstrap_local_state(settings)
        self.ui_data = UIDataService(settings)
        self.market_events = MarketEventService(settings)
        self.market_overview = MarketOverviewService(settings)
        self.logger = OperationLogger(operation_log_root(settings), "daily_report")

    def generate(self, *, pool_id: str = "default_core", market_date_us: date | None = None) -> DailyReportResult:
        generated_at = iso_beijing()
        refresh_summary = self._load_refresh_summary(pool_id, market_date_us=market_date_us)
        market_date = _report_market_date(refresh_summary, market_date_us)
        self.logger.info(
            "daily_report.generate.start",
            pool_id=pool_id,
            market_date_us=market_date.isoformat(),
            has_refresh_summary=refresh_summary is not None,
        )

        scanner = self.ui_data.scanner(pool_id)
        if market_date_us is None:
            refresh_summary = self._prefer_matching_refresh_summary(pool_id, market_date, refresh_summary)
        overview = self.market_overview.build(market_date_us=market_date, generated_at_beijing=generated_at)
        events = self.market_events.load_events(start=market_date, end=market_date + timedelta(days=14))
        markdown = self._render_markdown(
            pool_id=pool_id,
            market_date_us=market_date,
            generated_at_beijing=generated_at,
            refresh_summary=refresh_summary,
            scanner=scanner,
            overview=overview,
            events=events,
        )

        path = self._report_path(pool_id, market_date)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(markdown, encoding="utf-8")
        self.logger.info(
            "daily_report.generate.success",
            pool_id=pool_id,
            market_date_us=market_date.isoformat(),
            path=str(path),
            scanner_count=len(scanner.get("candidates", [])),
            market_events_count=len(events),
        )
        return DailyReportResult(
            pool_id=pool_id,
            market_date_us=market_date,
            generated_at_beijing=generated_at,
            path=path,
            scanner_count=len(scanner.get("candidates", [])),
            market_events_count=len(events),
        )

    def _render_markdown(
        self,
        *,
        pool_id: str,
        market_date_us: date,
        generated_at_beijing: str,
        refresh_summary: dict[str, Any] | None,
        scanner: dict[str, Any],
        overview: MarketOverview,
        events: list[dict[str, object]],
    ) -> str:
        pool = scanner.get("pool") if isinstance(scanner.get("pool"), dict) else {}
        summary = scanner.get("summary") if isinstance(scanner.get("summary"), dict) else {}
        candidates = [item for item in scanner.get("candidates", []) if isinstance(item, dict)]
        candidate_buy = [item for item in candidates if item.get("action") == "候选买入"]
        watch = [item for item in candidates if item.get("action") == "继续观察"]
        risk = [item for item in candidates if item.get("action") in {"风险回避", "数据不足"}]
        refresh_counts = _refresh_history_counts(refresh_summary)

        sections = [
            f"# QuantPlatform 每日报告 - {market_date_us.isoformat()}",
            "",
            f"- 生成时间（北京时间）：{generated_at_beijing}",
            f"- 美股交易日（America/New_York）：{market_date_us.isoformat()}",
            f"- 股票池：{pool.get('name_zh') or pool.get('name') or pool_id}",
            f"- 数据源：本地 daily refresh / scanner / market events / processed parquet",
            "",
            "## 执行摘要",
            "",
            f"- 市场状态：{overview.summary.get('risk_state')}",
            f"- Scanner：候选买入 {summary.get('candidate_buy', 0)}，继续观察 {summary.get('watch', 0)}，风险回避 {summary.get('risk_avoid', 0)}，数据不足 {summary.get('insufficient_data', 0)}",
            f"- 历史刷新：成功 {refresh_counts['success']}，空/未达目标 {refresh_counts['empty']}，错误 {refresh_counts['error']}",
            f"- 未来 14 天市场事件：{len(events)} 条",
            "",
            "## 市场概览",
            "",
            f"- VIX 状态：{overview.summary.get('vix_state')}（收盘：{_number(overview.summary.get('vix_close'))}）",
            f"- 强势板块：{', '.join(overview.summary.get('top_sectors') or []) or '数据不足'}",
            f"- 弱势板块：{', '.join(overview.summary.get('weak_sectors') or []) or '数据不足'}",
            "",
            _render_market_table("指数与宏观代理", overview.indexes),
            "",
            _render_market_table("板块 ETF", overview.sectors),
            "",
            _render_missing_market_data(overview),
            "",
            "## Scanner 候选",
            "",
            _render_candidate_table("候选买入", candidate_buy[:10]),
            "",
            _render_candidate_table("继续观察 Top 10", watch[:10]),
            "",
            _render_candidate_table("风险回避 / 数据不足", risk[:10]),
            "",
            "## 近期市场事件",
            "",
            _render_event_table(events[:20]),
            "",
            "## 数据质量",
            "",
            _render_data_quality(refresh_summary, scanner),
            "",
            "## 给 AI 的分析提示",
            "",
            "```text",
            _render_ai_prompt(pool_id, market_date_us, overview, candidate_buy, watch, risk, events, refresh_counts),
            "```",
            "",
        ]
        return "\n".join(sections)

    def _load_refresh_summary(self, pool_id: str, *, market_date_us: date | None) -> dict[str, Any] | None:
        base = self.settings.storage.reference_dir / "system" / "daily_refresh"
        if market_date_us is not None:
            path = base / f"{pool_id}_{market_date_us.isoformat()}.json"
            return _load_json(path)
        matches = sorted(base.glob(f"{pool_id}_*.json"))
        if not matches:
            return None
        return _load_json(matches[-1])

    def _prefer_matching_refresh_summary(
        self,
        pool_id: str,
        market_date_us: date,
        current: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        if current and current.get("market_date_us") == market_date_us.isoformat():
            return current
        matched = self._load_refresh_summary(pool_id, market_date_us=market_date_us)
        return matched or current

    def _report_path(self, pool_id: str, market_date_us: date) -> Path:
        reports_dir = self.settings.storage.processed_dir.parent / "reports"
        if pool_id == "default_core":
            return reports_dir / f"daily_{market_date_us.isoformat()}.md"
        return reports_dir / f"daily_{pool_id}_{market_date_us.isoformat()}.md"


def _render_market_table(title: str, rows: list[Any]) -> str:
    lines = [
        f"### {title}",
        "",
        "| 标的 | 日期 | 收盘 | 1日 | 5日 | 20日 | SMA50距离 | RSI14 | 状态 |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for item in rows:
        if item.data_status != "ok":
            lines.append(f"| {item.name} | - | - | - | - | - | - | - | {item.trend_state} |")
            continue
        lines.append(
            "| "
            + " | ".join(
                [
                    item.name,
                    item.latest_date_us or "-",
                    _money(item.close),
                    _pct(item.change_1d_pct),
                    _pct(item.change_5d_pct),
                    _pct(item.change_20d_pct),
                    _pct(item.distance_sma50_pct),
                    _number(item.rsi14),
                    item.trend_state,
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def _render_missing_market_data(overview: MarketOverview) -> str:
    missing_indexes = overview.summary.get("missing_indexes") or []
    missing_sectors = overview.summary.get("missing_sectors") or []
    if not missing_indexes and not missing_sectors:
        return "市场概览数据完整。"
    return "\n".join(
        [
            "市场概览缺失项：",
            f"- 指数/宏观代理缺失：{', '.join(missing_indexes) if missing_indexes else '无'}",
            f"- 板块 ETF 缺失：{', '.join(missing_sectors) if missing_sectors else '无'}",
            "- 这些标的需要先进入历史数据更新范围，日报才能展示完整轮动信息。",
        ]
    )


def _render_candidate_table(title: str, rows: list[dict[str, Any]]) -> str:
    lines = [
        f"### {title}",
        "",
        "| 标的 | 分数 | 动量排名 | 动作 | 风险 | 趋势 | RSI | MACD | 成交量 | 日期 |",
        "| --- | ---: | ---: | --- | --- | --- | --- | --- | --- | --- |",
    ]
    if not rows:
        lines.append("| - | - | - | - | - | - | - | - | - | - |")
        return "\n".join(lines)
    for item in rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(item.get("symbol") or "-"),
                    _plain(item.get("score")),
                    _rank_pct(item.get("momentum_rank_pct")),
                    str(item.get("action") or "-"),
                    str(item.get("risk_level") or "-"),
                    str(item.get("trend_state") or "-"),
                    str(item.get("rsi_state") or "-"),
                    str(item.get("macd_state") or "-"),
                    str(item.get("volume_state") or "-"),
                    str(item.get("latest_history_date_us") or "-"),
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def _render_event_table(events: list[dict[str, object]]) -> str:
    lines = [
        "| 日期/时间 | 重要性 | 来源 | 事件 |",
        "| --- | --- | --- | --- |",
    ]
    if not events:
        lines.append("| - | - | - | 未来窗口内暂无事件 |")
        return "\n".join(lines)
    for event in events:
        lines.append(
            "| "
            + " | ".join(
                [
                    _event_time_beijing(event.get("event_time")),
                    str(event.get("importance") or "-"),
                    str(event.get("source") or "-"),
                    str(event.get("title") or "-").replace("|", "/"),
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def _render_data_quality(refresh_summary: dict[str, Any] | None, scanner: dict[str, Any]) -> str:
    scanner_summary = scanner.get("summary") if isinstance(scanner.get("summary"), dict) else {}
    refresh_counts = _refresh_history_counts(refresh_summary)
    lines = [
        f"- refresh summary：{refresh_summary.get('generated_at_beijing') if refresh_summary else '未找到'}",
        f"- scanner result：{scanner.get('scan_result_path') or '未写入'}",
        f"- 历史数据：success={refresh_counts['success']}，empty={refresh_counts['empty']}，error={refresh_counts['error']}",
        f"- scanner 数据不足：{scanner_summary.get('insufficient_data', 0)}",
        f"- scanner 高风险：{scanner_summary.get('high_risk', 0)}",
    ]
    if refresh_summary and refresh_counts["error"]:
        errors = [
            f"{symbol}: {item.get('error')}"
            for symbol, item in refresh_summary.get("history", {}).items()
            if isinstance(item, dict) and item.get("status") == "error"
        ]
        lines.append(f"- 错误标的：{'; '.join(errors[:10])}")
    return "\n".join(lines)


def _render_ai_prompt(
    pool_id: str,
    market_date_us: date,
    overview: MarketOverview,
    candidate_buy: list[dict[str, Any]],
    watch: list[dict[str, Any]],
    risk: list[dict[str, Any]],
    events: list[dict[str, object]],
    refresh_counts: dict[str, int],
) -> str:
    return "\n".join(
        [
            f"请基于 QuantPlatform {market_date_us.isoformat()} 美股收盘后日报，辅助分析股票池 {pool_id}。",
            f"市场状态：{overview.summary.get('risk_state')}。",
            f"VIX 状态：{overview.summary.get('vix_state')}。",
            f"候选买入：{', '.join(str(item.get('symbol')) for item in candidate_buy[:10]) or '无'}。",
            f"继续观察：{', '.join(str(item.get('symbol')) for item in watch[:10]) or '无'}。",
            f"风险/数据不足：{', '.join(str(item.get('symbol')) for item in risk[:10]) or '无'}。",
            f"未来事件数量：{len(events)}；历史刷新 success={refresh_counts['success']}, empty={refresh_counts['empty']}, error={refresh_counts['error']}。",
            "请不要直接给自动下单指令。请输出：1. 明天重点关注标的；2. 需要避开的风险；3. 需要补充确认的数据；4. 适合人工复盘的问题。",
        ]
    )


def _refresh_history_counts(refresh_summary: dict[str, Any] | None) -> dict[str, int]:
    counts = {"success": 0, "empty": 0, "error": 0}
    if not refresh_summary:
        return counts
    history = refresh_summary.get("history", {})
    if not isinstance(history, dict):
        return counts
    for item in history.values():
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or "")
        if status in counts:
            counts[status] += 1
    return counts


def _report_market_date(refresh_summary: dict[str, Any] | None, explicit_date: date | None) -> date:
    if explicit_date is not None:
        return explicit_date
    if refresh_summary and refresh_summary.get("market_date_us"):
        try:
            summary_date = date.fromisoformat(str(refresh_summary["market_date_us"]))
        except ValueError:
            summary_date = None
        else:
            latest_cursor = _latest_history_cursor_date(refresh_summary)
            counts = _refresh_history_counts(refresh_summary)
            if counts["success"] == 0 and latest_cursor is not None and latest_cursor < summary_date:
                return latest_cursor
            return summary_date
    return latest_completed_us_market_date(now_beijing())


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _money(value: object) -> str:
    number = _optional_float(value)
    return "-" if number is None else f"${number:,.2f}"


def _number(value: object) -> str:
    number = _optional_float(value)
    return "-" if number is None else f"{number:.2f}"


def _plain(value: object) -> str:
    if value is None:
        return "-"
    return str(value)


def _event_time_beijing(value: object) -> str:
    if value is None:
        return "-"
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return str(value)
    return to_beijing(parsed).isoformat()


def _latest_history_cursor_date(refresh_summary: dict[str, Any]) -> date | None:
    history = refresh_summary.get("history", {})
    if not isinstance(history, dict):
        return None
    dates: list[date] = []
    for item in history.values():
        if not isinstance(item, dict) or not item.get("cursor"):
            continue
        try:
            dates.append(date.fromisoformat(str(item["cursor"])))
        except ValueError:
            continue
    return max(dates) if dates else None


def _rank_pct(value: object) -> str:
    number = _optional_float(value)
    if number is None:
        return "-"
    return f"{number:.2f}%"


def _pct(value: object) -> str:
    number = _optional_float(value)
    if number is None:
        return "-"
    return f"{number:.2f}%"


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
