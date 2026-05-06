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
    json_path: Path
    scanner_count: int
    market_events_count: int
    holding_count: int = 0
    watchlist_count: int = 0


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
        report_payload = self._build_comprehensive_payload(
            pool_id=pool_id,
            market_date_us=market_date,
            generated_at_beijing=generated_at,
            refresh_summary=refresh_summary,
            scanner=scanner,
            overview=overview,
            events=events,
        )
        markdown = self._render_markdown(report_payload)

        path = self._report_path(pool_id, market_date)
        json_path = self._json_report_path(pool_id, market_date)
        path.parent.mkdir(parents=True, exist_ok=True)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(markdown, encoding="utf-8")
        json_path.write_text(json.dumps(report_payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        self.logger.info(
            "daily_report.generate.success",
            pool_id=pool_id,
            market_date_us=market_date.isoformat(),
            path=str(path),
            json_path=str(json_path),
            scanner_count=len(scanner.get("candidates", [])),
            market_events_count=len(events),
            holding_count=len(report_payload.get("holdings_analysis") or []),
            watchlist_count=len(report_payload.get("watchlist_monitor") or []),
        )
        return DailyReportResult(
            pool_id=pool_id,
            market_date_us=market_date,
            generated_at_beijing=generated_at,
            path=path,
            json_path=json_path,
            scanner_count=len(scanner.get("candidates", [])),
            market_events_count=len(events),
            holding_count=len(report_payload.get("holdings_analysis") or []),
            watchlist_count=len(report_payload.get("watchlist_monitor") or []),
        )

    def _build_comprehensive_payload(
        self,
        *,
        pool_id: str,
        market_date_us: date,
        generated_at_beijing: str,
        refresh_summary: dict[str, Any] | None,
        scanner: dict[str, Any],
        overview: MarketOverview,
        events: list[dict[str, object]],
    ) -> dict[str, Any]:
        pool = scanner.get("pool") if isinstance(scanner.get("pool"), dict) else {}
        summary = scanner.get("summary") if isinstance(scanner.get("summary"), dict) else {}
        candidates = [item for item in scanner.get("candidates", []) if isinstance(item, dict)]
        candidate_buy = [item for item in candidates if item.get("action") == "候选买入"]
        watch = [item for item in candidates if item.get("action") == "继续观察"]
        risk = [item for item in candidates if item.get("action") in {"风险回避", "数据不足"}]
        refresh_counts = _refresh_history_counts(refresh_summary)
        supplemental_outputs = _supplemental_outputs(refresh_summary)
        reports_dir = self.settings.storage.processed_dir.parent / "reports"
        account_health, account_health_path = _load_source_json(
            reports_dir,
            supplemental_outputs,
            key="account_health",
            directory="account_health",
            pattern="account_health_*.json",
        )
        options_advice, options_path = _load_source_json(
            reports_dir,
            supplemental_outputs,
            key="options_advice",
            directory="options_advice",
            pattern="options_advice_*.json",
        )
        macro_risk, macro_path = _load_source_json(
            reports_dir,
            supplemental_outputs,
            key="macro_risk",
            directory="macro_risk",
            pattern="macro_risk_*.json",
        )
        portfolio_strategy, portfolio_path = _load_source_json(
            reports_dir,
            supplemental_outputs,
            key="portfolio_strategy",
            directory="portfolio_strategy",
            pattern="longbridge_portfolio_strategy_*.json",
        )
        ai_sources = _ai_source_artifacts(supplemental_outputs)
        holding_symbols = _holding_symbols(account_health, portfolio_strategy)
        watchlist_symbols = _watchlist_symbols(portfolio_strategy)
        snapshots = _load_snapshots(self.settings, _ordered_unique([*holding_symbols, *watchlist_symbols]))
        scan_by_symbol = _items_by_symbol(candidates)
        portfolio_positions = _items_by_symbol((portfolio_strategy or {}).get("positions") if isinstance(portfolio_strategy, dict) else [])
        portfolio_watchlist = _items_by_symbol((portfolio_strategy or {}).get("watchlist") if isinstance(portfolio_strategy, dict) else [])
        account_positions = _items_by_symbol(
            ((account_health or {}).get("risk_assessment") or {}).get("positions")
            if isinstance((account_health or {}).get("risk_assessment"), dict)
            else []
        )
        position_actions = _items_by_symbol((account_health or {}).get("position_actions") if isinstance(account_health, dict) else [])
        options_by_symbol = _options_by_symbol(options_advice)
        news_by_symbol = _news_by_symbol(macro_risk)
        data_gaps: list[dict[str, Any]] = []
        holdings = [
            _holding_analysis(
                symbol,
                snapshot=snapshots.get(symbol),
                account_position=account_positions.get(symbol),
                portfolio_position=portfolio_positions.get(symbol),
                position_action=position_actions.get(symbol),
                scanner_item=scan_by_symbol.get(symbol),
                options=options_by_symbol.get(symbol, []),
                news=news_by_symbol.get(symbol, []),
                macro_risk=macro_risk,
                data_gaps=data_gaps,
            )
            for symbol in holding_symbols
        ]
        watchlist_monitor = [
            _watchlist_analysis(
                symbol,
                snapshot=snapshots.get(symbol),
                portfolio_watch=portfolio_watchlist.get(symbol),
                scanner_item=scan_by_symbol.get(symbol),
                options=options_by_symbol.get(symbol, []),
                news=news_by_symbol.get(symbol, []),
                macro_risk=macro_risk,
                data_gaps=data_gaps,
            )
            for symbol in watchlist_symbols
        ]

        return {
            "schema_version": "daily_comprehensive_report_v1",
            "report_metadata": {
                "title": "QuantPlatform 综合每日报告",
                "pool_id": pool_id,
                "pool_name": pool.get("name_zh") or pool.get("name") or pool_id,
                "generated_at_beijing": generated_at_beijing,
                "timezone": "Asia/Shanghai",
                "market_date_us": market_date_us.isoformat(),
                "market_timezone": "America/New_York",
                "execution_boundary": "read_only_analysis_no_auto_order",
            },
            "data_sources": {
                "primary": ["local_daily_refresh", "local_snapshots", "local_processed_yfinance_bars"],
                "read_only_external": ["Longbridge CLI read-only", "yfinance research data"],
                "source_artifacts": _source_artifacts(
                    refresh_summary=refresh_summary,
                    scanner=scanner,
                    account_health_path=account_health_path,
                    options_path=options_path,
                    macro_path=macro_path,
                    portfolio_path=portfolio_path,
                    ai_sources=ai_sources,
                ),
            },
            "data_update": {
                "refresh_summary_generated_at_beijing": refresh_summary.get("generated_at_beijing") if refresh_summary else None,
                "history_counts": refresh_counts,
                "history_coverage": _history_coverage_summary(refresh_summary),
                "snapshot_count": refresh_summary.get("snapshot_count") if refresh_summary else None,
                "supplemental_outputs": _compact_supplemental_outputs(supplemental_outputs),
                "daily_update_design": [
                    "每日刷新先更新 Longbridge 真实持仓/自选池，再刷新 yfinance 日线和本地快照。",
                    "综合日报读取本地结构化产物生成 JSON，Markdown 只是人工阅读层。",
                    "任何数据缺失都进入 data_gaps，不用占位结论替代真实数据。",
                ],
            },
            "executive_summary": {
                "market_state": overview.summary.get("risk_state"),
                "vix_state": overview.summary.get("vix_state"),
                "macro_risk_state": (macro_risk or {}).get("risk_state") if isinstance(macro_risk, dict) else None,
                "sentiment_state": (macro_risk or {}).get("sentiment_state") if isinstance(macro_risk, dict) else None,
                "scanner": {
                    "candidate_buy": summary.get("candidate_buy", 0),
                    "watch": summary.get("watch", 0),
                    "risk_avoid": summary.get("risk_avoid", 0),
                    "insufficient_data": summary.get("insufficient_data", 0),
                },
                "holdings": {
                    "count": len(holdings),
                    "risk_review": sum(1 for item in holdings if item.get("review_priority") in {"high", "medium"}),
                },
                "watchlist": {
                    "count": len(watchlist_monitor),
                    "entry_watch": sum(1 for item in watchlist_monitor if item.get("entry_opportunity_state") in {"重点关注", "候选买入"}),
                },
                "options": _options_summary(options_advice),
                "data_gap_count": len(data_gaps),
            },
            "market_context": {
                "overview_summary": overview.summary,
                "indexes": [_market_row_payload(item) for item in overview.indexes],
                "sectors": [_market_row_payload(item) for item in overview.sectors],
                "macro_risk": _compact_macro_risk(macro_risk),
            },
            "scanner_candidates": {
                "candidate_buy": candidate_buy[:20],
                "watch": watch[:20],
                "risk_or_data_issue": risk[:20],
            },
            "holdings_analysis": holdings,
            "watchlist_monitor": watchlist_monitor,
            "options_strategy_advice": _options_strategy_section(options_advice, options_by_symbol),
            "market_events": [_event_payload(event) for event in events[:30]],
            "ai_reading_contract": {
                "recommended_read_order": [
                    "executive_summary",
                    "market_context.macro_risk",
                    "holdings_analysis",
                    "watchlist_monitor",
                    "options_strategy_advice",
                    "data_update",
                    "data_gaps",
                ],
                "required_boundary": "manual_review_only_no_auto_order",
                "prompt": _render_ai_prompt(pool_id, market_date_us, overview, candidate_buy, watch, risk, events, refresh_counts),
            },
            "data_gaps": data_gaps,
        }

    def _render_markdown(self, report: dict[str, Any]) -> str:
        meta = report.get("report_metadata") if isinstance(report.get("report_metadata"), dict) else {}
        summary = report.get("executive_summary") if isinstance(report.get("executive_summary"), dict) else {}
        scanner_summary = summary.get("scanner") if isinstance(summary.get("scanner"), dict) else {}
        holdings_summary = summary.get("holdings") if isinstance(summary.get("holdings"), dict) else {}
        watchlist_summary = summary.get("watchlist") if isinstance(summary.get("watchlist"), dict) else {}
        options_summary = summary.get("options") if isinstance(summary.get("options"), dict) else {}
        market_context = report.get("market_context") if isinstance(report.get("market_context"), dict) else {}
        overview_summary = market_context.get("overview_summary") if isinstance(market_context.get("overview_summary"), dict) else {}
        scanner = report.get("scanner_candidates") if isinstance(report.get("scanner_candidates"), dict) else {}
        data_update = report.get("data_update") if isinstance(report.get("data_update"), dict) else {}
        source_artifacts = ((report.get("data_sources") or {}).get("source_artifacts") or []) if isinstance(report.get("data_sources"), dict) else []

        sections = [
            f"# QuantPlatform 综合每日报告 - {meta.get('market_date_us')}",
            "",
            f"- 生成时间（北京时间）：{meta.get('generated_at_beijing')}",
            f"- 美股交易日（America/New_York）：{meta.get('market_date_us')}",
            f"- 股票池：{meta.get('pool_name')}",
            "- 边界：只读分析，不自动下单、撤单或改单；所有交易动作必须人工在券商界面确认。",
            "- AI 读取：同名 `.json` 是结构化主报告，Markdown 是人工速读层。",
            "",
            "## 执行摘要",
            "",
            f"- 市场状态：{summary.get('market_state')}；宏观/新闻风险：{summary.get('macro_risk_state')}；情绪：{summary.get('sentiment_state')}",
            f"- Scanner：候选买入 {scanner_summary.get('candidate_buy', 0)}，继续观察 {scanner_summary.get('watch', 0)}，风险回避 {scanner_summary.get('risk_avoid', 0)}，数据不足 {scanner_summary.get('insufficient_data', 0)}",
            f"- 持仓：{holdings_summary.get('count', 0)} 个，需复核 {holdings_summary.get('risk_review', 0)} 个；自选：{watchlist_summary.get('count', 0)} 个，进场监控 {watchlist_summary.get('entry_watch', 0)} 个",
            f"- 期权：covered call {options_summary.get('covered_call_count', 0)}，cash-secured put {options_summary.get('cash_secured_put_count', 0)}，数据异常 {options_summary.get('error_count', 0)}",
            f"- 数据缺口：{summary.get('data_gap_count', 0)} 项",
            "",
            "## 市场概览",
            "",
            f"- VIX 状态：{overview_summary.get('vix_state')}（收盘：{_number(overview_summary.get('vix_close'))}）",
            f"- 强势板块：{', '.join(overview_summary.get('top_sectors') or []) or '数据不足'}",
            f"- 弱势板块：{', '.join(overview_summary.get('weak_sectors') or []) or '数据不足'}",
            "",
            _render_market_payload_table("指数与宏观代理", market_context.get("indexes") if isinstance(market_context.get("indexes"), list) else []),
            "",
            _render_market_payload_table("板块 ETF", market_context.get("sectors") if isinstance(market_context.get("sectors"), list) else []),
            "",
            _render_missing_market_payload(market_context),
            "",
            "## Scanner 候选",
            "",
            _render_candidate_table("候选买入", scanner.get("candidate_buy") if isinstance(scanner.get("candidate_buy"), list) else []),
            "",
            _render_candidate_table("继续观察 Top 10", scanner.get("watch") if isinstance(scanner.get("watch"), list) else []),
            "",
            _render_candidate_table("风险回避 / 数据不足", scanner.get("risk_or_data_issue") if isinstance(scanner.get("risk_or_data_issue"), list) else []),
            "",
            "## 持仓综合分析",
            "",
            _render_holdings_table(report.get("holdings_analysis") if isinstance(report.get("holdings_analysis"), list) else []),
            "",
            "## 自选股监控",
            "",
            _render_watchlist_table(report.get("watchlist_monitor") if isinstance(report.get("watchlist_monitor"), list) else []),
            "",
            "## 期权策略建议",
            "",
            _render_options_report_section(report.get("options_strategy_advice") if isinstance(report.get("options_strategy_advice"), dict) else {}),
            "",
            "## 近期市场事件",
            "",
            _render_event_table(report.get("market_events") if isinstance(report.get("market_events"), list) else []),
            "",
            "## 数据更新与 AI 读取结构",
            "",
            _render_data_update(data_update, source_artifacts),
            "",
            "## 数据缺口",
            "",
            _render_data_gaps(report.get("data_gaps") if isinstance(report.get("data_gaps"), list) else []),
            "",
            "## 给 AI 的分析提示",
            "",
            "```text",
            ((report.get("ai_reading_contract") or {}).get("prompt") if isinstance(report.get("ai_reading_contract"), dict) else ""),
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

    def _json_report_path(self, pool_id: str, market_date_us: date) -> Path:
        reports_dir = self.settings.storage.processed_dir.parent / "reports"
        if pool_id == "default_core":
            return reports_dir / f"daily_{market_date_us.isoformat()}.json"
        return reports_dir / f"daily_{pool_id}_{market_date_us.isoformat()}.json"


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


def _render_market_payload_table(title: str, rows: list[dict[str, Any]]) -> str:
    lines = [
        f"### {title}",
        "",
        "| 标的 | 日期 | 收盘 | 1日 | 5日 | 20日 | SMA50距离 | RSI14 | 状态 |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    if not rows:
        lines.append("| - | - | - | - | - | - | - | - | 数据不足 |")
        return "\n".join(lines)
    for item in rows:
        if item.get("data_status") != "ok":
            lines.append(f"| {item.get('name') or item.get('symbol') or '-'} | - | - | - | - | - | - | - | {item.get('trend_state') or '数据不足'} |")
            continue
        lines.append(
            "| "
            + " | ".join(
                [
                    str(item.get("name") or item.get("symbol") or "-"),
                    str(item.get("latest_date_us") or "-"),
                    _money(item.get("close")),
                    _pct(item.get("change_1d_pct")),
                    _pct(item.get("change_5d_pct")),
                    _pct(item.get("change_20d_pct")),
                    _pct(item.get("distance_sma50_pct")),
                    _number(item.get("rsi14")),
                    str(item.get("trend_state") or "-"),
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def _render_missing_market_payload(market_context: dict[str, Any]) -> str:
    summary = market_context.get("overview_summary") if isinstance(market_context.get("overview_summary"), dict) else {}
    missing_indexes = summary.get("missing_indexes") or []
    missing_sectors = summary.get("missing_sectors") or []
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


def _render_holdings_table(rows: list[dict[str, Any]]) -> str:
    lines = [
        "| 标的 | 复核 | 基本面 | 资金流代理 | 技术走势 | 情绪/新闻 | 期权 | 数据缺口 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    if not rows:
        lines.append("| - | - | - | - | - | - | - | 未找到真实持仓产物 |")
        return "\n".join(lines)
    for item in rows:
        fundamental = item.get("fundamental") if isinstance(item.get("fundamental"), dict) else {}
        flow = item.get("capital_flow") if isinstance(item.get("capital_flow"), dict) else {}
        technical = item.get("technical") if isinstance(item.get("technical"), dict) else {}
        sentiment = item.get("sentiment") if isinstance(item.get("sentiment"), dict) else {}
        options = item.get("options") if isinstance(item.get("options"), dict) else {}
        gaps = item.get("data_gaps") if isinstance(item.get("data_gaps"), list) else []
        lines.append(
            "| "
            + " | ".join(
                [
                    str(item.get("symbol") or "-"),
                    str(item.get("manual_review") or item.get("review_priority") or "-"),
                    _plain_table_text(str(fundamental.get("summary") or "-")),
                    _plain_table_text(str(flow.get("summary") or "-")),
                    _plain_table_text(str(technical.get("summary") or "-")),
                    _plain_table_text(str(sentiment.get("summary") or "-")),
                    _plain_table_text(str(options.get("summary") or "-")),
                    _plain_table_text("；".join(str(gap.get("field") or gap.get("message") or gap) for gap in gaps) or "-"),
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def _render_watchlist_table(rows: list[dict[str, Any]]) -> str:
    lines = [
        "| 标的 | 分组 | 机会状态 | 分数 | 技术/量能 | 情绪 | 人工动作 |",
        "| --- | --- | --- | ---: | --- | --- | --- |",
    ]
    if not rows:
        lines.append("| - | - | - | - | - | - | 未找到自选股产物 |")
        return "\n".join(lines)
    for item in rows:
        technical = item.get("technical") if isinstance(item.get("technical"), dict) else {}
        sentiment = item.get("sentiment") if isinstance(item.get("sentiment"), dict) else {}
        lines.append(
            "| "
            + " | ".join(
                [
                    str(item.get("symbol") or "-"),
                    _plain_table_text(" / ".join(item.get("watchlist_groups") or []) or "-"),
                    str(item.get("entry_opportunity_state") or "-"),
                    _plain(item.get("attention_score")),
                    _plain_table_text(str(technical.get("summary") or "-")),
                    _plain_table_text(str(sentiment.get("summary") or "-")),
                    _plain_table_text(str(item.get("manual_review") or "-")),
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def _render_options_report_section(payload: dict[str, Any]) -> str:
    lines = [
        f"- 总结：{payload.get('summary_text') or '未找到期权建议产物'}",
        f"- 账户现金担保口径：{(payload.get('account_summary') or {}).get('cash_for_cash_secured_put', '-') if isinstance(payload.get('account_summary'), dict) else '-'}",
        "",
        "| 标的 | 策略 | 决策 | Strike | 到期 | 年化 | 关键风险 |",
        "| --- | --- | --- | ---: | --- | ---: | --- |",
    ]
    rows = payload.get("ideas") if isinstance(payload.get("ideas"), list) else []
    if not rows:
        lines.append("| - | - | - | - | - | - | 暂无可展示建议 |")
    for item in rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(item.get("symbol") or "-"),
                    str(item.get("strategy") or "-"),
                    str(item.get("decision") or "-"),
                    _plain(item.get("strike")),
                    str(item.get("expiration") or "-"),
                    _pct(item.get("annualized_return_pct")),
                    _plain_table_text("；".join(item.get("warnings") or item.get("violations") or []) or str(item.get("reason") or "-")),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "- 其它策略：第一版只把 covered call 和 cash-secured put 纳入规则化日报；更复杂价差、跨式或滚仓策略需要先补合约流动性、IV、财报和组合风险校验。",
        ]
    )
    return "\n".join(lines)


def _render_data_update(data_update: dict[str, Any], source_artifacts: list[Any]) -> str:
    counts = data_update.get("history_counts") if isinstance(data_update.get("history_counts"), dict) else {}
    coverage = data_update.get("history_coverage") if isinstance(data_update.get("history_coverage"), dict) else {}
    lines = [
        f"- refresh summary：{data_update.get('refresh_summary_generated_at_beijing') or '未找到'}",
        f"- 历史刷新：success={counts.get('success', 0)}，empty={counts.get('empty', 0)}，error={counts.get('error', 0)}",
        f"- 历史覆盖：最早 {coverage.get('earliest_date') or '-'}，最新 {coverage.get('latest_date') or '-'}，最少行数 {coverage.get('min_rows') or 0}",
        f"- 快照数量：{data_update.get('snapshot_count') or '-'}",
        "- 结构化日报 JSON 是 AI 后续分析的优先入口。",
        "",
        "### 关键产物",
        "",
        "| 类型 | 路径 |",
        "| --- | --- |",
    ]
    for item in source_artifacts[:12]:
        if isinstance(item, dict):
            lines.append(f"| {item.get('type') or '-'} | {_plain_table_text(str(item.get('path') or '-'))} |")
    return "\n".join(lines)


def _render_data_gaps(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "- 暂无结构化数据缺口。"
    lines = ["| 标的/范围 | 字段 | 缺口 | 后续数据源 |", "| --- | --- | --- | --- |"]
    for item in rows[:30]:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(item.get("symbol") or item.get("scope") or "-"),
                    str(item.get("field") or "-"),
                    _plain_table_text(str(item.get("message") or "-")),
                    _plain_table_text(str(item.get("next_source") or "-")),
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
                    str(event.get("event_time_beijing") or _event_time_beijing(event.get("event_time"))),
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
    coverage = _history_coverage_summary(refresh_summary)
    lines = [
        f"- refresh summary：{refresh_summary.get('generated_at_beijing') if refresh_summary else '未找到'}",
        f"- scanner result：{scanner.get('scan_result_path') or '未写入'}",
        f"- 历史数据：success={refresh_counts['success']}，empty={refresh_counts['empty']}，error={refresh_counts['error']}",
        f"- 历史覆盖：最早 {coverage['earliest_date'] or '-'}，最新 {coverage['latest_date'] or '-'}，最少行数 {coverage['min_rows']}",
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


def _render_supplemental_outputs(outputs: dict[str, Any]) -> str:
    if not outputs:
        return "\n".join(
            [
                "- 尚未找到收盘后补充分析。请先运行新的 `make daily-refresh`，它会生成账户健康、期权建议、AI 解读和日报。",
                "- 注意：这些模块只读取账户和行情数据，不产生自动下单指令。",
            ]
        )

    lines = [
        "| 模块 | 状态 | 关键结果 | 产物 |",
        "| --- | --- | --- | --- |",
    ]
    for key in [
        "longbridge_pool_sync",
        "account_health",
        "options_advice",
        "macro_risk",
        "ai_dashboard",
        "ai_account_health",
        "ai_options_advice",
    ]:
        payload = outputs.get(key)
        if not isinstance(payload, dict):
            continue
        lines.append(
            "| "
            + " | ".join(
                [
                    _supplemental_label(key),
                    str(payload.get("status") or "-"),
                    _supplemental_key_result(key, payload),
                    _supplemental_artifact(payload),
                ]
            )
            + " |"
        )

    excerpts: list[str] = []
    for key in ["ai_dashboard", "ai_account_health", "ai_options_advice"]:
        payload = outputs.get(key)
        if isinstance(payload, dict):
            excerpt = _markdown_excerpt(payload.get("markdown_path"), title=_supplemental_label(key))
            if excerpt:
                excerpts.append(excerpt)
    if excerpts:
        lines.extend(["", "### AI 摘要摘录", "", *excerpts])
    return "\n".join(lines)


def _supplemental_outputs(refresh_summary: dict[str, Any] | None) -> dict[str, Any]:
    if not refresh_summary:
        return {}
    outputs = refresh_summary.get("supplemental_outputs")
    return outputs if isinstance(outputs, dict) else {}


def _supplemental_label(key: str) -> str:
    return {
        "longbridge_pool_sync": "Longbridge 持仓/自选池",
        "account_health": "账户健康与风控",
        "options_advice": "持仓期权策略",
        "macro_risk": "宏观/新闻风险",
        "ai_dashboard": "AI 股票池解读",
        "ai_account_health": "AI 账户风控解读",
        "ai_options_advice": "AI 期权建议解读",
    }.get(key, key)


def _supplemental_key_result(key: str, payload: dict[str, Any]) -> str:
    if payload.get("status") == "error":
        return _plain_table_text(str(payload.get("error") or "error"))
    if key == "longbridge_pool_sync":
        return _plain_table_text(
            f"持仓 {payload.get('positions', '-')} / 自选 {payload.get('watchlist', '-')} / 合并 {payload.get('combined', '-')}"
        )
    if key == "account_health":
        return _plain_table_text(
            f"score={payload.get('health_score', '-')} state={payload.get('health_state', '-')} warnings={payload.get('warning_count', '-')}"
        )
    if key == "options_advice":
        return _plain_table_text(
            f"positions={payload.get('position_count', '-')} advice={payload.get('advice_count', '-')} errors={payload.get('error_count', '-')}"
        )
    if key == "macro_risk":
        return _plain_table_text(
            f"risk={payload.get('risk_state', '-')} sentiment={payload.get('sentiment_state', '-')} news={payload.get('news_item_count', '-')}"
        )
    if key.startswith("ai_"):
        return _plain_table_text(f"model_status={payload.get('model_status', '-')}")
    return "-"


def _supplemental_artifact(payload: dict[str, Any]) -> str:
    path = payload.get("markdown_path") or payload.get("path") or payload.get("core_pool_path") or payload.get("json_path")
    return _plain_table_text(str(path or "-"))


def _markdown_excerpt(path_value: object, *, title: str, max_lines: int = 14) -> str:
    if not path_value:
        return ""
    path = Path(str(path_value))
    if not path.exists():
        return ""
    lines = []
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("# "):
            continue
        lines.append(line)
        if len(lines) >= max_lines:
            break
    if not lines:
        return ""
    return "\n".join([f"#### {title}", "", *lines])


def _load_source_json(
    reports_dir: Path,
    outputs: dict[str, Any],
    *,
    key: str,
    directory: str,
    pattern: str,
) -> tuple[dict[str, Any] | None, Path | None]:
    output = outputs.get(key) if isinstance(outputs.get(key), dict) else {}
    path_value = output.get("json_path") if isinstance(output, dict) else None
    if path_value:
        path = Path(str(path_value))
        payload = _load_json(path)
        if payload is not None:
            return payload, path
    path = _latest_file(reports_dir / directory, pattern)
    if path is None:
        return None, None
    return _load_json(path), path


def _latest_file(directory: Path, pattern: str) -> Path | None:
    candidates = sorted(directory.glob(pattern))
    return candidates[-1] if candidates else None


def _ai_source_artifacts(outputs: dict[str, Any]) -> list[dict[str, str]]:
    artifacts: list[dict[str, str]] = []
    for key in ["ai_dashboard", "ai_account_health", "ai_options_advice"]:
        payload = outputs.get(key)
        if not isinstance(payload, dict):
            continue
        for path_key in ["json_path", "markdown_path"]:
            if payload.get(path_key):
                artifacts.append({"type": key, "path": str(payload[path_key])})
    return artifacts


def _source_artifacts(
    *,
    refresh_summary: dict[str, Any] | None,
    scanner: dict[str, Any],
    account_health_path: Path | None,
    options_path: Path | None,
    macro_path: Path | None,
    portfolio_path: Path | None,
    ai_sources: list[dict[str, str]],
) -> list[dict[str, str]]:
    artifacts: list[dict[str, str]] = []
    if scanner.get("scan_result_path"):
        artifacts.append({"type": "scanner", "path": str(scanner["scan_result_path"])})
    if refresh_summary and refresh_summary.get("dashboard_path"):
        artifacts.append({"type": "snapshot_dashboard", "path": str(refresh_summary["dashboard_path"])})
    for artifact_type, path in [
        ("account_health", account_health_path),
        ("options_advice", options_path),
        ("macro_risk", macro_path),
        ("portfolio_strategy", portfolio_path),
    ]:
        if path is not None:
            artifacts.append({"type": artifact_type, "path": str(path)})
    artifacts.extend(ai_sources)
    return artifacts


def _compact_supplemental_outputs(outputs: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for key, payload in outputs.items():
        if not isinstance(payload, dict):
            continue
        compact[key] = {
            item_key: payload.get(item_key)
            for item_key in (
                "status",
                "generated_at_beijing",
                "positions",
                "watchlist",
                "combined",
                "position_count",
                "watchlist_count",
                "advice_count",
                "error_count",
                "health_score",
                "health_state",
                "risk_state",
                "sentiment_state",
                "model_status",
                "json_path",
                "markdown_path",
                "path",
            )
            if item_key in payload
        }
    return compact


def _holding_symbols(account_health: dict[str, Any] | None, portfolio_strategy: dict[str, Any] | None) -> list[str]:
    symbols: list[str] = []
    if isinstance(account_health, dict):
        risk = account_health.get("risk_assessment") if isinstance(account_health.get("risk_assessment"), dict) else {}
        positions = risk.get("positions") if isinstance(risk.get("positions"), list) else []
        symbols.extend(str(item.get("symbol") or "") for item in positions if isinstance(item, dict))
    if isinstance(portfolio_strategy, dict):
        positions = portfolio_strategy.get("positions") if isinstance(portfolio_strategy.get("positions"), list) else []
        symbols.extend(str(item.get("symbol") or "") for item in positions if isinstance(item, dict))
    return _ordered_unique([_normalize_symbol(symbol) for symbol in symbols if symbol])


def _watchlist_symbols(portfolio_strategy: dict[str, Any] | None) -> list[str]:
    if not isinstance(portfolio_strategy, dict):
        return []
    watchlist = portfolio_strategy.get("watchlist") if isinstance(portfolio_strategy.get("watchlist"), list) else []
    return _ordered_unique([_normalize_symbol(str(item.get("symbol") or "")) for item in watchlist if isinstance(item, dict)])


def _load_snapshots(settings: Settings, symbols: list[str]) -> dict[str, dict[str, Any]]:
    snapshots: dict[str, dict[str, Any]] = {}
    for symbol in symbols:
        path = settings.storage.processed_dir / "snapshots" / f"{symbol}.json"
        payload = _load_json(path)
        if isinstance(payload, dict):
            snapshots[symbol] = payload
    return snapshots


def _items_by_symbol(items: object) -> dict[str, dict[str, Any]]:
    if not isinstance(items, list):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        symbol = _normalize_symbol(str(item.get("symbol") or ""))
        if symbol:
            result[symbol] = item
    return result


def _options_by_symbol(payload: dict[str, Any] | None) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    if not isinstance(payload, dict):
        return result
    for item in payload.get("positions") or []:
        if not isinstance(item, dict):
            continue
        symbol = _normalize_symbol(str(item.get("symbol") or ""))
        if not symbol:
            continue
        suggestions = [suggestion for suggestion in item.get("suggestions") or [] if isinstance(suggestion, dict)]
        if suggestions:
            result.setdefault(symbol, []).extend(suggestions)
    return result


def _news_by_symbol(payload: dict[str, Any] | None) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    if not isinstance(payload, dict):
        return result
    for item in payload.get("news_items") or []:
        if not isinstance(item, dict):
            continue
        symbol = _normalize_symbol(str(item.get("symbol") or ""))
        if symbol:
            result.setdefault(symbol, []).append(item)
    return result


def _holding_analysis(
    symbol: str,
    *,
    snapshot: dict[str, Any] | None,
    account_position: dict[str, Any] | None,
    portfolio_position: dict[str, Any] | None,
    position_action: dict[str, Any] | None,
    scanner_item: dict[str, Any] | None,
    options: list[dict[str, Any]],
    news: list[dict[str, Any]],
    macro_risk: dict[str, Any] | None,
    data_gaps: list[dict[str, Any]],
) -> dict[str, Any]:
    item_gaps: list[dict[str, Any]] = []
    fundamental = _fundamental_analysis(symbol, snapshot, item_gaps)
    capital_flow = _capital_flow_analysis(symbol, snapshot, scanner_item, portfolio_position, item_gaps)
    fund_holdings = _fund_holdings_analysis(symbol, snapshot, item_gaps)
    technical = _technical_analysis(snapshot, scanner_item, portfolio_position)
    sentiment = _sentiment_analysis(symbol, macro_risk, scanner_item, portfolio_position, news)
    option_summary = _symbol_options_summary(options)
    review_priority = _holding_review_priority(account_position, portfolio_position, scanner_item)
    for gap in item_gaps:
        data_gaps.append(gap)
    return {
        "symbol": symbol,
        "name": _first_non_empty(
            (snapshot or {}).get("company_name"),
            (account_position or {}).get("name"),
            (portfolio_position or {}).get("name"),
        ),
        "position": {
            "quantity": _first_non_empty((account_position or {}).get("quantity"), (portfolio_position or {}).get("quantity")),
            "market_value": _first_non_empty((account_position or {}).get("market_value"), (portfolio_position or {}).get("market_value")),
            "weight_pct": (account_position or {}).get("weight_pct"),
            "unrealized_pl_pct": _first_non_empty(
                (account_position or {}).get("unrealized_pl_pct"),
                (portfolio_position or {}).get("unrealized_pl_pct"),
            ),
            "cost_price": _first_non_empty((account_position or {}).get("cost_price"), (portfolio_position or {}).get("cost_price")),
            "current_price": _first_non_empty((account_position or {}).get("current_price"), (portfolio_position or {}).get("current_price"), (snapshot or {}).get("current_price")),
        },
        "review_priority": review_priority,
        "manual_review": _holding_manual_review(review_priority, account_position, portfolio_position, position_action),
        "fundamental": fundamental,
        "capital_flow": capital_flow,
        "fund_holdings": fund_holdings,
        "technical": technical,
        "sentiment": sentiment,
        "options": option_summary,
        "risk": {
            "risk_flags": (portfolio_position or {}).get("risk_flags") or (account_position or {}).get("flags") or [],
            "position_action": position_action,
        },
        "data_gaps": item_gaps,
    }


def _watchlist_analysis(
    symbol: str,
    *,
    snapshot: dict[str, Any] | None,
    portfolio_watch: dict[str, Any] | None,
    scanner_item: dict[str, Any] | None,
    options: list[dict[str, Any]],
    news: list[dict[str, Any]],
    macro_risk: dict[str, Any] | None,
    data_gaps: list[dict[str, Any]],
) -> dict[str, Any]:
    item_gaps: list[dict[str, Any]] = []
    _fundamental_analysis(symbol, snapshot, item_gaps)
    technical = _technical_analysis(snapshot, scanner_item, portfolio_watch)
    sentiment = _sentiment_analysis(symbol, macro_risk, scanner_item, portfolio_watch, news)
    for gap in item_gaps:
        if gap.get("field") in {"snapshot", "fundamental"}:
            data_gaps.append(gap)
    scanner_action = (scanner_item or {}).get("action")
    attention_state = (portfolio_watch or {}).get("attention_state")
    entry_state = "重点关注" if attention_state == "重点关注" or scanner_action == "候选买入" else attention_state or scanner_action or "继续观察"
    return {
        "symbol": symbol,
        "name": _first_non_empty((snapshot or {}).get("company_name"), (portfolio_watch or {}).get("name")),
        "watchlist_groups": (portfolio_watch or {}).get("watchlist_groups") or [],
        "entry_opportunity_state": entry_state,
        "attention_score": (portfolio_watch or {}).get("attention_score") or (scanner_item or {}).get("score"),
        "current_price": _first_non_empty((portfolio_watch or {}).get("current_price"), (snapshot or {}).get("current_price")),
        "technical": technical,
        "sentiment": sentiment,
        "options": _symbol_options_summary(options),
        "manual_review": (portfolio_watch or {}).get("manual_review") or _watchlist_manual_review(entry_state),
        "data_gaps": item_gaps,
    }


def _fundamental_analysis(symbol: str, snapshot: dict[str, Any] | None, gaps: list[dict[str, Any]]) -> dict[str, Any]:
    if not snapshot:
        gaps.append(_gap(symbol, "snapshot", "缺少本地股票快照，无法生成基本面概况。", "daily-refresh / yfinance snapshot"))
        return {"data_status": "missing", "summary": "缺少本地快照", "metrics": {}}
    metrics = {
        "company_name": snapshot.get("company_name"),
        "sector": snapshot.get("sector"),
        "industry": snapshot.get("industry"),
        "market_cap": snapshot.get("market_cap"),
        "trailing_pe": snapshot.get("trailing_pe"),
        "forward_pe": snapshot.get("forward_pe"),
        "next_earnings_date": snapshot.get("next_earnings_date"),
        "currency": snapshot.get("currency"),
    }
    missing = [key for key in ("sector", "industry", "market_cap", "trailing_pe") if metrics.get(key) in (None, "")]
    if missing:
        gaps.append(_gap(symbol, "fundamental", f"基本面字段缺失：{', '.join(missing)}。", "yfinance quote snapshot / future fundamentals cache"))
    summary = (
        f"{metrics.get('sector') or '行业未知'} / {metrics.get('industry') or '细分未知'}，"
        f"市值 {_compact_money(metrics.get('market_cap'))}，PE TTM {_compact_number(metrics.get('trailing_pe'))}，"
        f"下次财报 {metrics.get('next_earnings_date') or '-'}"
    )
    return {"data_status": "partial" if missing else "ok", "summary": summary, "metrics": metrics}


def _capital_flow_analysis(
    symbol: str,
    snapshot: dict[str, Any] | None,
    scanner_item: dict[str, Any] | None,
    portfolio_item: dict[str, Any] | None,
    gaps: list[dict[str, Any]],
) -> dict[str, Any]:
    indicators = (snapshot or {}).get("indicators") if isinstance((snapshot or {}).get("indicators"), dict) else {}
    change_pct = _first_float((snapshot or {}).get("change_percent"), (scanner_item or {}).get("change_percent"))
    volume_ratio = _first_float(indicators.get("volume_ratio_20"), (scanner_item or {}).get("volume_ratio_20"))
    volume_zscore = _first_float(indicators.get("volume_zscore_60"), (scanner_item or {}).get("volume_zscore_60"))
    latest_volume = _first_float((snapshot or {}).get("latest_volume"))
    data_status = "proxy"
    if change_pct is None or (volume_ratio is None and volume_zscore is None and latest_volume is None):
        gaps.append(_gap(symbol, "capital_flow", "当前数据源没有真实逐笔资金流；本报告只能使用价格与成交量代理指标。", "Longbridge capital flow permission / future provider"))
        data_status = "proxy_limited"
    direction = "中性"
    if volume_zscore is not None and volume_zscore >= 1 and change_pct is not None and change_pct > 0:
        direction = "放量上涨，资金流代理偏流入"
    elif volume_zscore is not None and volume_zscore >= 1 and change_pct is not None and change_pct < 0:
        direction = "放量下跌，资金流代理偏流出"
    elif volume_ratio is not None and volume_ratio >= 1.5 and change_pct is not None and change_pct > 0:
        direction = "成交量高于均值且价格上行"
    elif change_pct is not None and change_pct < -3:
        direction = "价格明显回落，需检查卖压"
    summary = f"{direction}；涨跌 {_pct(change_pct)}，量比20 {_compact_number(volume_ratio)}，量能z60 {_compact_number(volume_zscore)}"
    return {
        "data_status": data_status,
        "source_type": "price_volume_proxy_not_true_capital_flow",
        "summary": summary,
        "metrics": {
            "change_percent": change_pct,
            "latest_volume": latest_volume,
            "volume_ratio_20": volume_ratio,
            "volume_zscore_60": volume_zscore,
            "scanner_volume_state": (scanner_item or {}).get("volume_state"),
            "portfolio_signal_net_score": ((portfolio_item or {}).get("signals") or {}).get("net_score") if isinstance((portfolio_item or {}).get("signals"), dict) else None,
        },
    }


def _fund_holdings_analysis(symbol: str, snapshot: dict[str, Any] | None, gaps: list[dict[str, Any]]) -> dict[str, Any]:
    extra = snapshot or {}
    metrics = {
        "held_percent_institutions": _first_float(
            extra.get("held_percent_institutions"),
            extra.get("heldPercentInstitutions"),
            extra.get("institutional_ownership_pct"),
        ),
        "held_percent_insiders": _first_float(
            extra.get("held_percent_insiders"),
            extra.get("heldPercentInsiders"),
            extra.get("insider_ownership_pct"),
        ),
        "institutional_holders": extra.get("institutional_holders") if isinstance(extra.get("institutional_holders"), list) else [],
        "fund_holders": extra.get("fund_holders") if isinstance(extra.get("fund_holders"), list) else [],
    }
    if not any(value for value in metrics.values()):
        gaps.append(_gap(symbol, "fund_holdings", "当前本地日报缓存未包含基金/机构持仓明细，不能判断机构增减持。", "yfinance holders cache / SEC 13F"))
        return {
            "data_status": "missing",
            "summary": "机构/基金持仓数据未接入；不生成增减持判断",
            "metrics": metrics,
        }
    summary = (
        f"机构持股 {_pct(metrics.get('held_percent_institutions'))}，内部人 {_pct(metrics.get('held_percent_insiders'))}，"
        f"机构条目 {len(metrics.get('institutional_holders') or [])}，基金条目 {len(metrics.get('fund_holders') or [])}"
    )
    return {"data_status": "partial", "summary": summary, "metrics": metrics}


def _technical_analysis(snapshot: dict[str, Any] | None, scanner_item: dict[str, Any] | None, portfolio_item: dict[str, Any] | None) -> dict[str, Any]:
    indicators = (snapshot or {}).get("indicators") if isinstance((snapshot or {}).get("indicators"), dict) else {}
    signals = (portfolio_item or {}).get("signals") if isinstance((portfolio_item or {}).get("signals"), dict) else {}
    scanner_summary = {
        key: (scanner_item or {}).get(key)
        for key in ("score", "action", "risk_level", "trend_state", "rsi_state", "macd_state", "volume_state", "momentum_rank_pct")
    }
    indicator_summary = {
        key: indicators.get(key)
        for key in (
            "sma_20",
            "sma_50",
            "rsi_14",
            "macd",
            "macd_signal",
            "macd_histogram",
            "atr_14",
            "ret_20d_skip5",
            "ret_60d_skip5",
            "ret_120d_skip5",
            "volume_ratio_20",
            "volume_zscore_60",
        )
        if key in indicators
    }
    summary = (
        f"{scanner_summary.get('action') or '未扫描'}，趋势 {scanner_summary.get('trend_state') or '-'}，"
        f"RSI {scanner_summary.get('rsi_state') or _compact_number(indicator_summary.get('rsi_14'))}，"
        f"MACD {scanner_summary.get('macd_state') or '-'}，信号净分 {signals.get('net_score', 0)}"
    )
    return {
        "summary": summary,
        "scanner": scanner_summary,
        "indicators": indicator_summary,
        "signals": signals,
        "latest_history_date_us": (snapshot or {}).get("latest_history_date_us") or (((portfolio_item or {}).get("data") or {}).get("latest_history_date_us") if isinstance((portfolio_item or {}).get("data"), dict) else None),
    }


def _sentiment_analysis(
    symbol: str,
    macro_risk: dict[str, Any] | None,
    scanner_item: dict[str, Any] | None,
    portfolio_item: dict[str, Any] | None,
    news: list[dict[str, Any]],
) -> dict[str, Any]:
    macro_state = (macro_risk or {}).get("risk_state") if isinstance(macro_risk, dict) else None
    sentiment_state = (macro_risk or {}).get("sentiment_state") if isinstance(macro_risk, dict) else None
    risk_level = (scanner_item or {}).get("risk_level")
    health = (portfolio_item or {}).get("health_state") or (portfolio_item or {}).get("attention_state")
    summary = (
        f"宏观 {macro_state or '-'} / 情绪 {sentiment_state or '-'}；"
        f"Scanner 风险 {risk_level or '-'}；新闻 {len(news)} 条"
    )
    if health:
        summary += f"；组合状态 {health}"
    return {
        "summary": summary,
        "macro_risk_state": macro_state,
        "sentiment_state": sentiment_state,
        "scanner_risk_level": risk_level,
        "portfolio_state": health,
        "news_items": news[:5],
    }


def _symbol_options_summary(options: list[dict[str, Any]]) -> dict[str, Any]:
    if not options:
        return {"summary": "暂无该标的期权建议", "ideas": []}
    ideas = [_compact_option_idea(option) for option in options]
    good = [idea for idea in ideas if idea.get("decision") == "符合策略"]
    summary = f"{len(ideas)} 条建议，符合策略 {len(good)} 条；策略：{', '.join(_ordered_unique(str(item.get('strategy')) for item in ideas if item.get('strategy'))) or '-'}"
    return {"summary": summary, "ideas": ideas}


def _options_summary(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"covered_call_count": 0, "cash_secured_put_count": 0, "suggestion_count": 0, "error_count": 0}
    options_by_symbol = _options_by_symbol(payload)
    ideas = [idea for ideas in options_by_symbol.values() for idea in ideas]
    return {
        "covered_call_count": sum(1 for idea in ideas if idea.get("strategy") == "covered_call"),
        "cash_secured_put_count": sum(1 for idea in ideas if idea.get("strategy") == "cash_secured_put"),
        "suggestion_count": len(ideas),
        "error_count": len(payload.get("errors") or []),
    }


def _options_strategy_section(payload: dict[str, Any] | None, options_by_symbol: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    ideas = [
        {"symbol": symbol, **_compact_option_idea(option)}
        for symbol, options in options_by_symbol.items()
        for option in options
    ]
    summary = _options_summary(payload)
    summary_text = (
        f"共 {summary['suggestion_count']} 条期权建议，covered call {summary['covered_call_count']}，"
        f"cash-secured put {summary['cash_secured_put_count']}，异常 {summary['error_count']}。"
        if isinstance(payload, dict)
        else "未找到期权建议产物。"
    )
    return {
        "summary": summary,
        "summary_text": summary_text,
        "account_summary": payload.get("account_summary") if isinstance(payload, dict) else None,
        "ideas": ideas,
        "errors": payload.get("errors") if isinstance(payload, dict) else [],
        "boundary": "read_only_options_research_no_auto_order",
    }


def _compact_option_idea(option: dict[str, Any]) -> dict[str, Any]:
    return {
        "strategy": option.get("strategy"),
        "decision": option.get("decision"),
        "reason": option.get("reason"),
        "strike": option.get("strike"),
        "expiration": option.get("expiration"),
        "dte": option.get("dte"),
        "bid": option.get("bid"),
        "ask": option.get("ask"),
        "mid": option.get("mid"),
        "premium_income": option.get("premium_income"),
        "annualized_return_pct": option.get("annualized_return_pct"),
        "capital_required": option.get("capital_required"),
        "warnings": option.get("warnings") or option.get("data_warnings") or [],
        "violations": option.get("violations") or [],
    }


def _holding_review_priority(
    account_position: dict[str, Any] | None,
    portfolio_position: dict[str, Any] | None,
    scanner_item: dict[str, Any] | None,
) -> str:
    if (scanner_item or {}).get("risk_level") == "高" or (portfolio_position or {}).get("health_state") == "风险复核":
        return "high"
    flags = (portfolio_position or {}).get("risk_flags") or (account_position or {}).get("flags") or []
    if flags or (account_position or {}).get("concentration_status") == "breach":
        return "medium"
    return "normal"


def _holding_manual_review(
    priority: str,
    account_position: dict[str, Any] | None,
    portfolio_position: dict[str, Any] | None,
    position_action: dict[str, Any] | None,
) -> str:
    if position_action and position_action.get("action"):
        return str(position_action["action"])
    if portfolio_position and portfolio_position.get("manual_review"):
        return str(portfolio_position["manual_review"])
    if priority == "high":
        return "优先人工复核仓位、止损和事件风险。"
    if priority == "medium":
        return "保持观察，确认风险提示是否需要控仓。"
    return "常规复盘，不生成自动交易动作。"


def _watchlist_manual_review(state: str) -> str:
    if state in {"重点关注", "候选买入"}:
        return "加入明日重点观察，但仍需交易计划、止损和市场状态确认。"
    if state == "暂缓":
        return "暂缓进场，等待趋势或量能修复。"
    return "持续监控，等待更明确的趋势、量能和风险条件。"


def _market_row_payload(item: Any) -> dict[str, Any]:
    return {
        "symbol": getattr(item, "symbol", None),
        "name": getattr(item, "name", None),
        "data_status": getattr(item, "data_status", None),
        "latest_date_us": getattr(item, "latest_date_us", None),
        "close": getattr(item, "close", None),
        "change_1d_pct": getattr(item, "change_1d_pct", None),
        "change_5d_pct": getattr(item, "change_5d_pct", None),
        "change_20d_pct": getattr(item, "change_20d_pct", None),
        "distance_sma50_pct": getattr(item, "distance_sma50_pct", None),
        "rsi14": getattr(item, "rsi14", None),
        "trend_state": getattr(item, "trend_state", None),
    }


def _compact_macro_risk(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    return {
        "generated_at_beijing": payload.get("generated_at_beijing"),
        "market_date_us": payload.get("market_date_us"),
        "risk_state": payload.get("risk_state"),
        "sentiment_state": payload.get("sentiment_state"),
        "scanner_filter_hint": payload.get("scanner_filter_hint"),
        "news_item_count": len(payload.get("news_items") or []),
        "warnings": payload.get("warnings") or [],
    }


def _event_payload(event: dict[str, object]) -> dict[str, object]:
    return {
        "event_time_beijing": _event_time_beijing(event.get("event_time")),
        "importance": event.get("importance"),
        "source": event.get("source"),
        "title": event.get("title"),
        "symbol": event.get("symbol"),
        "event_type": event.get("event_type"),
    }


def _gap(symbol: str, field: str, message: str, next_source: str) -> dict[str, str]:
    return {"symbol": symbol, "field": field, "message": message, "next_source": next_source}


def _normalize_symbol(symbol: str) -> str:
    return str(symbol or "").strip().upper().replace(".US", "")


def _ordered_unique(items: list[str] | Any) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        value = str(item or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _first_non_empty(*values: object) -> object | None:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def _first_float(*values: object) -> float | None:
    for value in values:
        parsed = _optional_float(value)
        if parsed is not None:
            return parsed
    return None


def _compact_money(value: object) -> str:
    number = _optional_float(value)
    if number is None:
        return "-"
    if abs(number) >= 1_000_000_000_000:
        return f"${number / 1_000_000_000_000:.2f}T"
    if abs(number) >= 1_000_000_000:
        return f"${number / 1_000_000_000:.2f}B"
    if abs(number) >= 1_000_000:
        return f"${number / 1_000_000:.2f}M"
    return f"${number:,.0f}"


def _compact_number(value: object) -> str:
    number = _optional_float(value)
    return "-" if number is None else f"{number:.2f}"


def _plain_table_text(value: str) -> str:
    return value.replace("|", "/").replace("\n", " ")[:240]


def _history_coverage_summary(refresh_summary: dict[str, Any] | None) -> dict[str, Any]:
    summary: dict[str, Any] = {"earliest_date": None, "latest_date": None, "min_rows": 0}
    if not refresh_summary:
        return summary
    history = refresh_summary.get("history", {})
    if not isinstance(history, dict):
        return summary
    earliest_dates: list[str] = []
    latest_dates: list[str] = []
    row_counts: list[int] = []
    for item in history.values():
        if not isinstance(item, dict) or item.get("status") != "success":
            continue
        if item.get("earliest_date"):
            earliest_dates.append(str(item["earliest_date"]))
        if item.get("latest_date"):
            latest_dates.append(str(item["latest_date"]))
        if item.get("total_rows") is not None:
            try:
                row_counts.append(int(item["total_rows"]))
            except (TypeError, ValueError):
                pass
    return {
        "earliest_date": min(earliest_dates) if earliest_dates else None,
        "latest_date": max(latest_dates) if latest_dates else None,
        "min_rows": min(row_counts) if row_counts else 0,
    }


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
