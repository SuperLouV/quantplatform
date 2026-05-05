"""Macro, sentiment, and news risk snapshot for daily preparation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from quant_platform.clients.longbridge_cli import LongbridgeCLIClient
from quant_platform.config import Settings
from quant_platform.services.bootstrap import bootstrap_local_state
from quant_platform.services.market_overview import MarketOverviewService
from quant_platform.services.operation_log import OperationLogger, operation_log_root
from quant_platform.time_utils import iso_beijing


@dataclass(slots=True)
class MacroRiskRunResult:
    generated_at_beijing: str
    market_date_us: str
    risk_state: str
    sentiment_state: str
    news_item_count: int
    json_path: Path
    markdown_path: Path
    warnings: list[str]


class MacroRiskService:
    """Build a conservative market regime context from local bars and Longbridge.

    The module is intentionally read-only. It does not create signals or
    trading actions; it only describes risk conditions that should gate later
    scanner and option ideas.
    """

    def __init__(self, settings: Settings, longbridge_client: LongbridgeCLIClient | None = None) -> None:
        self.settings = settings
        self.artifacts = bootstrap_local_state(settings)
        self.longbridge_client = longbridge_client or LongbridgeCLIClient.from_data_config(settings.data)
        self.logger = OperationLogger(operation_log_root(settings), "macro_risk")

    def generate(
        self,
        *,
        market_date_us: date,
        symbols: list[str] | None = None,
        news_limit_per_symbol: int = 3,
    ) -> MacroRiskRunResult:
        self.logger.info("macro_risk.generate.start", market_date_us=market_date_us.isoformat())
        warnings: list[str] = []
        generated_at = iso_beijing()
        overview = MarketOverviewService(self.settings).build(
            market_date_us=market_date_us,
            generated_at_beijing=generated_at,
        )
        market_temperature = self._safe_market_temperature(warnings)
        news_items = self._safe_news(symbols or [], news_limit_per_symbol, warnings)
        sentiment_state = _sentiment_state(market_temperature)
        payload = {
            "analysis_id": f"macro_risk:{datetime.now(tz=UTC).strftime('%Y%m%dT%H%M%SZ')}",
            "generated_at_beijing": generated_at,
            "timezone": "Asia/Shanghai",
            "market_date_us": market_date_us.isoformat(),
            "market_timezone": "America/New_York",
            "execution_boundary": "read_only_macro_news_risk_no_auto_order",
            "data_sources": {
                "market_overview": "local_processed_bars",
                "market_temperature": "longbridge_cli_market_temp",
                "news": "longbridge_cli_news",
            },
            "market_overview": overview.to_dict(),
            "market_temperature": market_temperature,
            "sentiment_state": sentiment_state,
            "risk_state": _combined_risk_state(overview.summary.get("risk_state"), sentiment_state),
            "scanner_filter_hint": _scanner_filter_hint(overview.summary.get("risk_state"), sentiment_state),
            "news_items": news_items,
            "warnings": warnings,
        }
        json_path, markdown_path = self._write_outputs(payload)
        self.logger.info(
            "macro_risk.generate.success",
            market_date_us=market_date_us.isoformat(),
            risk_state=payload["risk_state"],
            sentiment_state=sentiment_state,
            news_items=len(news_items),
            warnings=len(warnings),
            json_path=str(json_path),
        )
        return MacroRiskRunResult(
            generated_at_beijing=generated_at,
            market_date_us=market_date_us.isoformat(),
            risk_state=str(payload["risk_state"]),
            sentiment_state=sentiment_state,
            news_item_count=len(news_items),
            json_path=json_path,
            markdown_path=markdown_path,
            warnings=warnings,
        )

    def _safe_market_temperature(self, warnings: list[str]) -> dict[str, Any] | None:
        try:
            payload = self.longbridge_client.fetch_market_temperature()
            return payload if isinstance(payload, dict) else None
        except Exception as exc:  # noqa: BLE001 - Longbridge sentiment is useful but not required.
            warnings.append(f"Longbridge market-temp 读取失败：{exc}")
            self.logger.error("macro_risk.market_temp.error", error=str(exc))
            return None

    def _safe_news(self, symbols: list[str], limit: int, warnings: list[str]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for symbol in _unique_symbols(symbols)[:8]:
            try:
                for item in self.longbridge_client.fetch_news(symbol, limit=limit):
                    items.append(_compact_news_item(symbol, item))
            except Exception as exc:  # noqa: BLE001 - one symbol's news should not break the daily package.
                warnings.append(f"{symbol} Longbridge news 读取失败：{exc}")
                self.logger.error("macro_risk.news.error", symbol=symbol, error=str(exc))
        return items

    def _write_outputs(self, payload: dict[str, Any]) -> tuple[Path, Path]:
        output_dir = self.settings.storage.processed_dir.parent / "reports" / "macro_risk"
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
        json_path = output_dir / f"macro_risk_{timestamp}.json"
        markdown_path = output_dir / f"macro_risk_{timestamp}.md"
        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        markdown_path.write_text(_render_markdown(payload), encoding="utf-8")
        return json_path, markdown_path


def latest_macro_risk_report(settings: Settings) -> dict[str, Any] | None:
    directory = settings.storage.processed_dir.parent / "reports" / "macro_risk"
    candidates = sorted(directory.glob("macro_risk_*.json"))
    if not candidates:
        return None
    try:
        payload = json.loads(candidates[-1].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _sentiment_state(payload: dict[str, Any] | None) -> str:
    value = _find_temperature_value(payload)
    if value is None:
        return "unknown"
    if value >= 75:
        return "overheated"
    if value >= 60:
        return "risk_on"
    if value <= 25:
        return "fear"
    if value <= 40:
        return "risk_off"
    return "neutral"


def _find_temperature_value(payload: dict[str, Any] | None) -> float | None:
    if not payload:
        return None
    for key in ("temperature", "score", "value", "market_temperature", "index"):
        value = _optional_float(payload.get(key))
        if value is not None:
            return value
    for value in payload.values():
        if isinstance(value, dict):
            nested = _find_temperature_value(value)
            if nested is not None:
                return nested
    return None


def _combined_risk_state(market_state: object, sentiment_state: str) -> str:
    market_text = str(market_state or "")
    if "Risk Off" in market_text or sentiment_state in {"fear", "risk_off"}:
        return "risk_off"
    if sentiment_state == "overheated":
        return "caution_overheated"
    if "Risk On" in market_text and sentiment_state in {"risk_on", "neutral", "unknown"}:
        return "risk_on"
    return "neutral"


def _scanner_filter_hint(market_state: object, sentiment_state: str) -> str:
    combined = _combined_risk_state(market_state, sentiment_state)
    if combined == "risk_off":
        return "降低 scanner 候选优先级，优先看持仓防守、止损和现金比例。"
    if combined == "caution_overheated":
        return "市场情绪偏热，候选可观察但不应放大仓位或追高。"
    if combined == "risk_on":
        return "趋势环境允许观察强势候选，但仍需用仓位和 ATR 风控过滤。"
    return "市场方向不明确，候选需要更多信号确认。"


def _compact_news_item(symbol: str, item: dict[str, Any]) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "id": item.get("id") or item.get("news_id"),
        "title": item.get("title") or item.get("headline"),
        "source": item.get("source") or item.get("publisher"),
        "published_at": item.get("published_at") or item.get("time") or item.get("datetime"),
        "url": item.get("url"),
    }


def _unique_symbols(symbols: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for symbol in symbols:
        normalized = str(symbol or "").upper().replace(".US", "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _render_markdown(payload: dict[str, Any]) -> str:
    overview = payload.get("market_overview") if isinstance(payload.get("market_overview"), dict) else {}
    summary = overview.get("summary") if isinstance(overview.get("summary"), dict) else {}
    lines = [
        "# 宏观、情绪与新闻风险快照",
        "",
        f"- 生成时间（北京时间）：{payload.get('generated_at_beijing')}",
        f"- 市场交易日（美东）：{payload.get('market_date_us')}",
        f"- 综合风险状态：{payload.get('risk_state')}",
        f"- Longbridge 情绪状态：{payload.get('sentiment_state')}",
        f"- 市场趋势状态：{summary.get('risk_state')}",
        f"- VIX 状态：{summary.get('vix_state')}",
        f"- Scanner 过滤提示：{payload.get('scanner_filter_hint')}",
        "",
        "## 新闻监控",
    ]
    news = payload.get("news_items") if isinstance(payload.get("news_items"), list) else []
    if news:
        lines.extend(
            f"- {item.get('symbol')}：{item.get('title') or '未命名新闻'}"
            for item in news[:20]
            if isinstance(item, dict)
        )
    else:
        lines.append("- 暂无 Longbridge 新闻条目或当前环境无法读取。")
    warnings = payload.get("warnings") if isinstance(payload.get("warnings"), list) else []
    if warnings:
        lines.extend(["", "## 数据警告", *[f"- {warning}" for warning in warnings]])
    lines.extend(
        [
            "",
            "## 边界",
            "- 本报告只用于人工复盘和风险过滤，不是买卖指令。",
            "- 新闻只保存元数据，不保存账户敏感信息。",
        ]
    )
    return "\n".join(lines) + "\n"


def _optional_float(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
