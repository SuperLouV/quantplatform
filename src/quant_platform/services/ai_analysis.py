"""Structured analysis helpers for snapshot-level reasoning."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, fields
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from quant_platform.clients.openai_compatible import OpenAICompatibleClient, extract_chat_text
from quant_platform.config import Settings
from quant_platform.core.product_models import AIAnalysisResult, StockPoolSnapshot, StockSnapshot
from quant_platform.services.bootstrap import bootstrap_local_state
from quant_platform.time_utils import iso_beijing


class AIAnalysisService:
    """Prepare structured AI analysis outputs without binding to a specific model provider yet."""

    def create_placeholder_for_snapshot(self, snapshot: StockSnapshot) -> AIAnalysisResult:
        key_points = [
            f"screening_status={snapshot.screening_status}",
            f"latest_close={snapshot.latest_close}",
            f"pool_count={len(snapshot.pool_ids)}",
        ]
        warnings = list(snapshot.screening_reasons)
        return AIAnalysisResult(
            analysis_id=f"stock:{snapshot.symbol}:{_utcnow().strftime('%Y%m%dT%H%M%SZ')}",
            target_type="stock_snapshot",
            target_id=snapshot.symbol,
            risk_level=_infer_risk(snapshot.screening_status),
            recommendation=_infer_recommendation(snapshot.screening_status),
            summary="Placeholder analysis result. Replace with model-backed interpretation later.",
            key_points=key_points,
            warnings=warnings,
            generated_at=_utcnow(),
        )

    def create_placeholder_for_pool(self, pool: StockPoolSnapshot) -> AIAnalysisResult:
        return AIAnalysisResult(
            analysis_id=f"pool:{pool.pool_id}:{_utcnow().strftime('%Y%m%dT%H%M%SZ')}",
            target_type="stock_pool",
            target_id=pool.pool_id,
            risk_level="unknown",
            recommendation="review",
            summary="Placeholder pool-level analysis result. Replace with model-backed interpretation later.",
            key_points=[
                f"member_count={len(pool.members)}",
                f"pool_type={pool.pool_type}",
                f"source={pool.source}",
            ],
            warnings=[],
            generated_at=_utcnow(),
        )

    def create_simple_market_analysis(
        self,
        snapshot: StockSnapshot,
        history_points: list[dict[str, object]],
    ) -> AIAnalysisResult:
        closes = [
            float(point["close"])
            for point in history_points
            if point.get("close") is not None
        ]

        latest_close = snapshot.latest_close
        sma20 = _simple_average(closes[-20:]) if len(closes) >= 20 else None
        sma50 = _simple_average(closes[-50:]) if len(closes) >= 50 else None
        return_20d = _return_rate(closes[-21], closes[-1]) if len(closes) >= 21 else None
        volatility_20d = _volatility(closes[-21:]) if len(closes) >= 21 else None

        trend_score = 0
        if latest_close is not None and sma20 is not None and latest_close > sma20:
            trend_score += 1
        if sma20 is not None and sma50 is not None and sma20 > sma50:
            trend_score += 1
        if return_20d is not None and return_20d > 0:
            trend_score += 1

        risk_score = 0
        warnings: list[str] = []
        if volatility_20d is not None and volatility_20d > 0.035:
            risk_score += 1
            warnings.append("近20个交易日波动偏高。")
        if snapshot.avg_dollar_volume is not None and snapshot.avg_dollar_volume < 20_000_000:
            risk_score += 1
            warnings.append("平均成交额偏低，流动性一般。")
        if snapshot.next_earnings_date:
            warnings.append("存在临近财报事件，需留意事件风险。")

        if trend_score >= 3:
            recommendation = "buy_watch"
            summary = "价格结构偏强，适合作为重点跟踪的候选买点。"
        elif trend_score == 2:
            recommendation = "watch"
            summary = "趋势中性偏强，适合继续观察，不建议追高。"
        else:
            recommendation = "avoid"
            summary = "趋势条件不足，当前更适合等待而不是主动介入。"

        if risk_score >= 2:
            risk_level = "high"
        elif risk_score == 1:
            risk_level = "medium"
        else:
            risk_level = "low"

        key_points = [
            _format_key_point("最新价格", latest_close),
            _format_key_point("SMA20", sma20),
            _format_key_point("SMA50", sma50),
            _format_percent_point("20日涨跌幅", return_20d),
            _format_percent_point("20日波动率", volatility_20d),
        ]

        return AIAnalysisResult(
            analysis_id=f"market:{snapshot.symbol}:{_utcnow().strftime('%Y%m%dT%H%M%SZ')}",
            target_type="stock_snapshot",
            target_id=snapshot.symbol,
            risk_level=risk_level,
            recommendation=recommendation,
            summary=summary,
            key_points=[point for point in key_points if point is not None],
            warnings=warnings,
            generated_at=_utcnow(),
        )


def _infer_risk(status: str) -> str:
    if status == "passed":
        return "medium"
    if status == "pending_data":
        return "unknown"
    return "high"


def _infer_recommendation(status: str) -> str:
    if status == "passed":
        return "review"
    if status == "pending_data":
        return "collect_data"
    return "avoid"


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


def _simple_average(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _return_rate(start: float, end: float) -> float | None:
    if start in (0, None):
        return None
    return (end - start) / start


def _volatility(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    returns = []
    for index in range(1, len(values)):
        prev = values[index - 1]
        curr = values[index]
        if prev in (0, None):
            continue
        returns.append((curr - prev) / prev)
    if len(returns) < 2:
        return None
    mean = sum(returns) / len(returns)
    variance = sum((value - mean) ** 2 for value in returns) / (len(returns) - 1)
    return variance ** 0.5


def _format_key_point(label: str, value: float | None) -> str | None:
    if value is None:
        return None
    return f"{label}={value:.2f}"


def _format_percent_point(label: str, value: float | None) -> str | None:
    if value is None:
        return None
    return f"{label}={value * 100:.2f}%"


@dataclass(slots=True)
class AutomatedAIAnalysisRunResult:
    generated_at_beijing: str
    json_path: Path
    markdown_path: Path
    snapshot_count: int
    model_status: str
    warnings: list[str]


class AutomatedAIAnalysisService:
    """Generate deterministic context plus optional model interpretation.

    The rule layer always produces a structured report. The model layer is
    optional and only reads the deterministic payload; it never produces orders
    or execution authority.
    """

    def __init__(self, settings: Settings, client: OpenAICompatibleClient | None = None) -> None:
        self.settings = settings
        self.artifacts = bootstrap_local_state(settings)
        self.client = client

    def analyze_dashboard(
        self,
        *,
        pool_id: str = "longbridge_core",
        max_symbols: int = 40,
        use_model: bool = True,
    ) -> AutomatedAIAnalysisRunResult:
        snapshots = self._load_dashboard_snapshots(max_symbols=max_symbols)
        portfolio = self._load_latest_portfolio_strategy()
        portfolio_by_symbol = {
            str(item.get("symbol") or "").upper(): item
            for item in portfolio.get("positions", [])
            if isinstance(item, dict)
        }

        analyses = [
            self._analyze_snapshot(snapshot, portfolio_by_symbol.get(snapshot.symbol.upper()))
            for snapshot in snapshots
            if pool_id in snapshot.pool_ids or pool_id == "all" or not snapshot.pool_ids
        ]
        warnings: list[str] = []
        if not analyses:
            warnings.append("没有找到可分析的本地快照，先运行 daily-refresh 或 pool-refresh。")

        model_status = "skipped"
        model_summary: dict[str, Any] = {
            "provider": self.settings.ai.provider,
            "model": self.settings.ai.model,
            "summary": "",
            "raw_text": "",
            "warnings": [],
        }
        if use_model and analyses:
            model_status, model_summary = self._run_model_layer(analyses)

        payload = {
            "analysis_id": f"ai_analysis:{datetime.now(tz=UTC).strftime('%Y%m%dT%H%M%SZ')}",
            "generated_at_beijing": iso_beijing(),
            "timezone": "Asia/Shanghai",
            "pool_id": pool_id,
            "execution_boundary": "read_only_analysis_no_auto_order",
            "model_status": model_status,
            "model": model_summary,
            "summary": _summarize_analyses(analyses),
            "analyses": analyses,
            "warnings": warnings,
        }
        json_path, markdown_path = self._write_outputs(payload)
        return AutomatedAIAnalysisRunResult(
            generated_at_beijing=str(payload["generated_at_beijing"]),
            json_path=json_path,
            markdown_path=markdown_path,
            snapshot_count=len(analyses),
            model_status=model_status,
            warnings=warnings + list(model_summary.get("warnings") or []),
        )

    def _load_dashboard_snapshots(self, *, max_symbols: int) -> list[StockSnapshot]:
        dashboard_path = self.settings.storage.reference_dir / "system" / "dashboard_data.json"
        snapshots: list[StockSnapshot] = []
        if dashboard_path.exists():
            payload = json.loads(dashboard_path.read_text(encoding="utf-8"))
            for item in payload.get("snapshots", [])[:max_symbols]:
                if isinstance(item, dict):
                    snapshots.append(_snapshot_from_mapping(item))
            return snapshots

        snapshot_dir = self.settings.storage.processed_dir / "snapshots"
        for path in sorted(snapshot_dir.glob("*.json"))[:max_symbols]:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                snapshots.append(_snapshot_from_mapping(payload))
        return snapshots

    def _load_latest_portfolio_strategy(self) -> dict[str, Any]:
        output_dir = self.settings.storage.processed_dir.parent / "reports" / "portfolio_strategy"
        candidates = sorted(output_dir.glob("longbridge_portfolio_strategy_*.json"))
        if not candidates:
            return {"positions": []}
        try:
            payload = json.loads(candidates[-1].read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"positions": []}
        return payload if isinstance(payload, dict) else {"positions": []}

    def _analyze_snapshot(self, snapshot: StockSnapshot, portfolio_item: dict[str, Any] | None) -> dict[str, Any]:
        technical = _technical_interpretation(snapshot)
        health = _holding_health(snapshot, portfolio_item, technical)
        risks = _risk_warnings(snapshot, portfolio_item, technical, health)
        risk_level = _analysis_risk_level(risks, health)
        recommendation = _analysis_recommendation(technical, health, risks)
        key_points = [
            f"技术状态：{technical['state']}",
            f"持仓健康度：{health['score']} / 100（{health['state']}）",
            f"趋势依据：{technical['summary']}",
        ]
        result = AIAnalysisResult(
            analysis_id=f"stock:{snapshot.symbol}:{datetime.now(tz=UTC).strftime('%Y%m%dT%H%M%SZ')}",
            target_type="stock_snapshot",
            target_id=snapshot.symbol,
            risk_level=risk_level,
            recommendation=recommendation,
            summary=_analysis_summary(snapshot, technical, health, risks),
            key_points=key_points,
            warnings=risks,
            generated_at=_utcnow(),
        )
        return {
            "result": _serialize_ai_result(result),
            "snapshot": _compact_snapshot(snapshot),
            "portfolio": _compact_portfolio_item(portfolio_item),
            "structured_report": {
                "technical_interpretation": technical,
                "holding_health": health,
                "risk_warnings": risks,
            },
            "markdown_summary": _render_symbol_markdown(result, technical, health, risks),
        }

    def _run_model_layer(self, analyses: list[dict[str, Any]]) -> tuple[str, dict[str, Any]]:
        config = self.settings.ai
        provider = (config.provider or "").strip().lower()
        model_summary: dict[str, Any] = {
            "provider": config.provider,
            "model": config.model,
            "summary": "",
            "raw_text": "",
            "warnings": [],
        }
        if provider in {"", "none", "off", "disabled"}:
            return "skipped", model_summary
        if not config.base_url:
            model_summary["warnings"].append("AI base_url 未配置，跳过模型层。")
            return "skipped", model_summary
        if provider in {"local", "local_openai", "ollama", "lmstudio"} and "deepseek.com" in config.base_url:
            model_summary["warnings"].append("本地 AI provider 仍使用默认 DeepSeek base_url，已跳过模型层。")
            return "skipped", model_summary
        if provider in {"deepseek", "openai"} and not config.api_key:
            model_summary["warnings"].append("托管 AI provider 缺少 API key，已只生成规则层分析。")
            return "skipped", model_summary

        client = self.client or OpenAICompatibleClient.from_ai_config(config)
        prompt_payload = {
            "execution_boundary": "read_only_analysis_no_auto_order",
            "instruction": "请基于结构化数据做保守中文研判，输出总体摘要、共同风险、需要用户人工确认的问题。不要给下单指令。",
            "analyses": analyses[:20],
        }
        messages = [
            {
                "role": "system",
                "content": "你是保守的美股研究助手，只解释结构化事实、风险和不确定性，不生成自动交易动作。",
            },
            {"role": "user", "content": json.dumps(prompt_payload, ensure_ascii=False, default=str)},
        ]
        try:
            response = client.chat(messages, temperature=0.2, max_tokens=1400)
            text = extract_chat_text(response)
        except Exception as exc:  # noqa: BLE001 - model failure must not block deterministic reports.
            model_summary["warnings"].append(f"模型调用失败：{exc}")
            return "error", model_summary
        model_summary["summary"] = text.strip()
        model_summary["raw_text"] = text
        return "success", model_summary

    def _write_outputs(self, payload: dict[str, Any]) -> tuple[Path, Path]:
        output_dir = self.settings.storage.processed_dir.parent / "reports" / "ai_analysis"
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
        json_path = output_dir / f"ai_analysis_{timestamp}.json"
        markdown_path = output_dir / f"ai_analysis_{timestamp}.md"
        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        markdown_path.write_text(_render_analysis_markdown(payload), encoding="utf-8")
        return json_path, markdown_path


def _snapshot_from_mapping(payload: dict[str, Any]) -> StockSnapshot:
    allowed = {field.name for field in fields(StockSnapshot)}
    data = {key: value for key, value in payload.items() if key in allowed}
    if data.get("as_of") and isinstance(data["as_of"], str):
        try:
            data["as_of"] = datetime.fromisoformat(data["as_of"])
        except ValueError:
            data["as_of"] = None
    return StockSnapshot(**data)


def _technical_interpretation(snapshot: StockSnapshot) -> dict[str, Any]:
    indicators = snapshot.indicators or {}
    price = _finite_float(snapshot.current_price) or _finite_float(snapshot.latest_close)
    sma20 = _finite_float(indicators.get("sma_20"))
    sma50 = _finite_float(indicators.get("sma_50"))
    rsi14 = _finite_float(indicators.get("rsi_14"))
    macd_histogram = _finite_float(indicators.get("macd_histogram"))
    atr14 = _finite_float(indicators.get("atr_14"))
    volume_ratio = _finite_float(indicators.get("volume_ratio_20"))

    positives: list[str] = []
    negatives: list[str] = []
    observations: list[str] = []
    score = 50
    if price is not None and sma20 is not None:
        if price >= sma20:
            score += 10
            positives.append("价格站上 SMA20。")
        else:
            score -= 12
            negatives.append("价格低于 SMA20，短线趋势偏弱。")
    if sma20 is not None and sma50 is not None:
        if sma20 >= sma50:
            score += 10
            positives.append("SMA20 高于 SMA50，中期趋势未明显破坏。")
        else:
            score -= 10
            negatives.append("SMA20 低于 SMA50，中期趋势承压。")
    if rsi14 is not None:
        if rsi14 >= 75:
            score -= 8
            observations.append("RSI14 偏高，追高风险上升。")
        elif rsi14 <= 35:
            score -= 3
            observations.append("RSI14 偏低，可能处在弱势或反弹观察区。")
        elif 45 <= rsi14 <= 65:
            score += 5
            observations.append("RSI14 处于相对中性区。")
    if macd_histogram is not None:
        if macd_histogram > 0:
            score += 6
            positives.append("MACD histogram 为正。")
        elif macd_histogram < 0:
            score -= 6
            negatives.append("MACD histogram 为负。")
    if volume_ratio is not None and volume_ratio >= 1.8:
        observations.append("成交量相对 20 日均量明显放大。")
    if atr14 is not None and price not in (None, 0):
        atr_pct = atr14 / price * 100
        if atr_pct >= 6:
            score -= 8
            negatives.append("ATR 占价格比例偏高，波动风险较大。")
    else:
        atr_pct = None

    bounded = _bounded(score)
    if bounded >= 70:
        state = "偏强"
    elif bounded >= 50:
        state = "中性"
    else:
        state = "偏弱"
    summary_parts = positives[:2] + negatives[:2] + observations[:1]
    return {
        "score": bounded,
        "state": state,
        "summary": "；".join(summary_parts) or "本地指标不足，无法形成充分技术面判断。",
        "price": price,
        "sma_20": sma20,
        "sma_50": sma50,
        "rsi_14": rsi14,
        "macd_histogram": macd_histogram,
        "atr_14": atr14,
        "atr_pct": _round_optional(atr_pct),
        "volume_ratio_20": volume_ratio,
        "positives": positives,
        "negatives": negatives,
        "observations": observations,
    }


def _holding_health(
    snapshot: StockSnapshot,
    portfolio_item: dict[str, Any] | None,
    technical: dict[str, Any],
) -> dict[str, Any]:
    if portfolio_item:
        score = _optional_int(portfolio_item.get("health_score"))
        state = str(portfolio_item.get("health_state") or "未知")
        return {
            "source": "portfolio_strategy",
            "score": score,
            "state": state,
            "quantity": portfolio_item.get("quantity"),
            "cost_price": portfolio_item.get("cost_price"),
            "unrealized_pl_pct": portfolio_item.get("unrealized_pl_pct"),
            "risk_flags": portfolio_item.get("risk_flags") or [],
        }

    score = int(technical.get("score") or 40)
    if snapshot.screening_status in {"data_error", "error"}:
        score -= 20
    elif snapshot.screening_status == "data_warning":
        score -= 10
    score = _bounded(score)
    if score >= 70:
        state = "健康"
    elif score >= 50:
        state = "观察"
    else:
        state = "风险复核"
    return {
        "source": "snapshot_indicators",
        "score": score,
        "state": state,
        "quantity": None,
        "cost_price": None,
        "unrealized_pl_pct": None,
        "risk_flags": [],
    }


def _risk_warnings(
    snapshot: StockSnapshot,
    portfolio_item: dict[str, Any] | None,
    technical: dict[str, Any],
    health: dict[str, Any],
) -> list[str]:
    warnings = list(snapshot.screening_reasons or [])
    warnings.extend(str(item) for item in health.get("risk_flags") or [])
    if snapshot.quote_provider_status and snapshot.quote_provider_status != "success":
        warnings.append("行情 provider 状态异常，需手工确认最新价格。")
    if not snapshot.indicators:
        warnings.append("缺少本地技术指标，AI 只能做有限解读。")
    if technical.get("state") == "偏弱":
        warnings.append("技术面偏弱，不适合把分析结果理解为买入信号。")
    if technical.get("atr_pct") is not None and float(technical["atr_pct"]) >= 6:
        warnings.append("ATR 波动率偏高，仓位和止损需要更保守。")
    if snapshot.next_earnings_date:
        warnings.append(f"存在财报日期字段：{snapshot.next_earnings_date}，需确认事件风险。")
    if portfolio_item is None:
        warnings.append("未匹配到真实持仓健康度，评分来自快照指标而非账户成本。")
    return list(dict.fromkeys(warnings))


def _analysis_risk_level(risks: list[str], health: dict[str, Any]) -> str:
    score = health.get("score")
    if score is None:
        return "unknown"
    if score < 45 or len(risks) >= 4:
        return "high"
    if score < 65 or risks:
        return "medium"
    return "low"


def _analysis_recommendation(technical: dict[str, Any], health: dict[str, Any], risks: list[str]) -> str:
    if health.get("score") is None:
        return "collect_data"
    if health["score"] < 45:
        return "risk_review"
    if technical.get("state") == "偏强" and len(risks) <= 2:
        return "watch"
    return "hold_review"


def _analysis_summary(
    snapshot: StockSnapshot,
    technical: dict[str, Any],
    health: dict[str, Any],
    risks: list[str],
) -> str:
    return (
        f"{snapshot.symbol} 技术面{technical['state']}，持仓健康度 {health['score']} / 100"
        f"（{health['state']}）。主要判断：{technical['summary']}。"
        f"风险提示 {len(risks)} 条，仍需人工复核。"
    )


def _serialize_ai_result(result: AIAnalysisResult) -> dict[str, Any]:
    payload = asdict(result)
    if result.generated_at is not None:
        payload["generated_at"] = result.generated_at.isoformat()
    return payload


def _compact_snapshot(snapshot: StockSnapshot) -> dict[str, Any]:
    return {
        "symbol": snapshot.symbol,
        "company_name": snapshot.company_name,
        "pool_ids": snapshot.pool_ids,
        "current_price": snapshot.current_price,
        "latest_close": snapshot.latest_close,
        "change_percent": snapshot.change_percent,
        "latest_volume": snapshot.latest_volume,
        "latest_history_date_us": snapshot.latest_history_date_us,
        "quote_provider": snapshot.quote_provider,
        "quote_provider_status": snapshot.quote_provider_status,
        "screening_status": snapshot.screening_status,
    }


def _compact_portfolio_item(item: dict[str, Any] | None) -> dict[str, Any] | None:
    if not item:
        return None
    return {
        "symbol": item.get("symbol"),
        "quantity": item.get("quantity"),
        "cost_price": item.get("cost_price"),
        "current_price": item.get("current_price"),
        "unrealized_pl_pct": item.get("unrealized_pl_pct"),
        "health_score": item.get("health_score"),
        "health_state": item.get("health_state"),
    }


def _render_symbol_markdown(
    result: AIAnalysisResult,
    technical: dict[str, Any],
    health: dict[str, Any],
    risks: list[str],
) -> str:
    risk_text = "；".join(risks[:4]) if risks else "暂无突出风险，但仍需人工确认。"
    return (
        f"### {result.target_id}\n\n"
        f"- 结论：{result.summary}\n"
        f"- 技术面：{technical['summary']}\n"
        f"- 健康度：{health['score']} / 100（{health['state']}）\n"
        f"- 风险：{risk_text}\n"
    )


def _summarize_analyses(analyses: list[dict[str, Any]]) -> dict[str, Any]:
    risk_counts: dict[str, int] = {}
    recommendation_counts: dict[str, int] = {}
    for item in analyses:
        result = item.get("result") if isinstance(item.get("result"), dict) else {}
        risk = str(result.get("risk_level") or "unknown")
        recommendation = str(result.get("recommendation") or "unknown")
        risk_counts[risk] = risk_counts.get(risk, 0) + 1
        recommendation_counts[recommendation] = recommendation_counts.get(recommendation, 0) + 1
    return {
        "snapshot_count": len(analyses),
        "risk_counts": risk_counts,
        "recommendation_counts": recommendation_counts,
    }


def _render_analysis_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# 自动化 AI 分析报告",
        "",
        f"- 生成时间（北京）：{payload.get('generated_at_beijing')}",
        f"- 股票池：{payload.get('pool_id')}",
        f"- 模型层状态：{payload.get('model_status')}",
        "- 边界：只读分析，不自动下单、撤单或改单",
        "",
        "## 总览",
        "",
        f"- 风险分布：{payload.get('summary', {}).get('risk_counts')}",
        f"- 建议分布：{payload.get('summary', {}).get('recommendation_counts')}",
    ]
    model = payload.get("model", {})
    if isinstance(model, dict) and model.get("summary"):
        lines.extend(["", "## 模型综合摘要", "", str(model["summary"])])
    lines.extend(["", "## 个股结构化摘要", ""])
    for item in payload.get("analyses", []):
        if isinstance(item, dict):
            lines.append(str(item.get("markdown_summary") or ""))
    if payload.get("warnings"):
        lines.extend(["", "## 数据提示", ""])
        lines.extend(f"- {warning}" for warning in payload.get("warnings", []))
    lines.extend(
        [
            "",
            "## 人工复核边界",
            "",
            "- AI 分析读取的是本地快照、指标和持仓健康度结构化产物。",
            "- 任何建议都不是自动交易指令，交易动作必须在券商界面人工确认。",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def _finite_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _optional_int(value: Any) -> int | None:
    number = _finite_float(value)
    return None if number is None else int(round(number))


def _bounded(value: float | int) -> int:
    return round(max(0, min(100, float(value))))


def _round_optional(value: float | None) -> float | None:
    return None if value is None else round(float(value), 2)
