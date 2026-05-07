"""Structured analysis helpers for model-backed research interpretation."""

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
    """Prepare lightweight deterministic analysis for UI and snapshot pipelines."""

    def create_basic_for_snapshot(self, snapshot: StockSnapshot) -> AIAnalysisResult:
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
            summary="基于本地快照字段生成的基础结构化分析；深度解读请使用 ai-stock。",
            key_points=key_points,
            warnings=warnings,
            generated_at=_utcnow(),
        )

    def create_basic_for_pool(self, pool: StockPoolSnapshot) -> AIAnalysisResult:
        return AIAnalysisResult(
            analysis_id=f"pool:{pool.pool_id}:{_utcnow().strftime('%Y%m%dT%H%M%SZ')}",
            target_type="stock_pool",
            target_id=pool.pool_id,
            risk_level="unknown",
            recommendation="review",
            summary="基于股票池元数据生成的基础结构化分析；深度解读请使用模型分析入口。",
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


@dataclass(slots=True)
class AIInterpretationRunResult:
    generated_at_beijing: str
    json_path: Path
    markdown_path: Path
    scenario: str
    target_id: str
    model_status: str
    source_paths: list[Path]
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
        account_payload, account_path = self._load_optional_latest_report("account_health", "account_health_*.json")
        portfolio_by_symbol = {
            str(item.get("symbol") or "").upper(): item
            for item in portfolio.get("positions", [])
            if isinstance(item, dict)
        }
        account_by_symbol = _account_positions_by_symbol(account_payload)

        analyses = [
            self._analyze_snapshot(
                snapshot,
                portfolio_by_symbol.get(snapshot.symbol.upper()) or account_by_symbol.get(_normalize_symbol(snapshot.symbol)),
            )
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
            "source_paths": [str(path) for path in [account_path] if path],
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

    def analyze_latest_account_health(self, *, use_model: bool = True) -> AIInterpretationRunResult:
        source_path = _latest_report_path(
            self.settings.storage.processed_dir.parent / "reports" / "account_health",
            "account_health_*.json",
        )
        source_payload = _read_json_object(source_path)
        context = _account_health_prompt_context(source_payload)
        return self._analyze_structured_context(
            scenario="account_health",
            target_id=str(source_payload.get("analysis_id") or "latest_account_health"),
            context=context,
            source_paths=[source_path],
            use_model=use_model,
            max_tokens=1800,
        )

    def analyze_latest_options_advice(self, *, use_model: bool = True) -> AIInterpretationRunResult:
        source_path = _latest_report_path(
            self.settings.storage.processed_dir.parent / "reports" / "options_advice",
            "options_advice_*.json",
        )
        source_payload = _read_json_object(source_path)
        context = _options_advice_prompt_context(source_payload)
        return self._analyze_structured_context(
            scenario="options_advice",
            target_id=str(source_payload.get("analysis_id") or "latest_options_advice"),
            context=context,
            source_paths=[source_path],
            use_model=use_model,
            max_tokens=1800,
        )

    def analyze_stock_technical(self, symbol: str, *, use_model: bool = True) -> AIInterpretationRunResult:
        normalized = symbol.upper().strip()
        if not normalized:
            raise ValueError("symbol is required.")
        snapshot, snapshot_path = self._load_stock_snapshot(normalized)
        account_payload, account_path = self._load_optional_latest_report("account_health", "account_health_*.json")
        options_payload, options_path = self._load_optional_latest_report("options_advice", "options_advice_*.json")
        context = _stock_prompt_context(
            snapshot,
            account_payload=account_payload,
            options_payload=options_payload,
        )
        source_paths = [snapshot_path]
        if account_path:
            source_paths.append(account_path)
        if options_path:
            source_paths.append(options_path)
        return self._analyze_structured_context(
            scenario="stock_technical",
            target_id=normalized,
            context=context,
            source_paths=source_paths,
            use_model=use_model,
            max_tokens=1600,
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

    def _load_stock_snapshot(self, symbol: str) -> tuple[StockSnapshot, Path]:
        snapshot_path = self.settings.storage.processed_dir / "snapshots" / f"{symbol}.json"
        if snapshot_path.exists():
            return _snapshot_from_mapping(_read_json_object(snapshot_path)), snapshot_path

        dashboard_path = self.settings.storage.reference_dir / "system" / "dashboard_data.json"
        if dashboard_path.exists():
            payload = _read_json_object(dashboard_path)
            for item in payload.get("snapshots") or []:
                if isinstance(item, dict) and str(item.get("symbol") or "").upper() == symbol:
                    return _snapshot_from_mapping(item), dashboard_path
        raise FileNotFoundError(f"缺少 {symbol} 本地快照；先运行 daily-refresh、pool-refresh 或 history/快照刷新。")

    def _load_optional_latest_report(self, folder_name: str, pattern: str) -> tuple[dict[str, Any] | None, Path | None]:
        directory = self.settings.storage.processed_dir.parent / "reports" / folder_name
        candidates = sorted(directory.glob(pattern))
        if not candidates:
            return None, None
        path = candidates[-1]
        try:
            return _read_json_object(path), path
        except (OSError, json.JSONDecodeError, ValueError):
            return None, path

    def _analyze_structured_context(
        self,
        *,
        scenario: str,
        target_id: str,
        context: dict[str, Any],
        source_paths: list[Path],
        use_model: bool,
        max_tokens: int,
    ) -> AIInterpretationRunResult:
        warnings: list[str] = []
        model_status = "skipped"
        model_text = ""
        prompt_payload = _build_model_prompt_payload(scenario=scenario, target_id=target_id, context=context)
        if use_model:
            model_status, model_text, model_warnings = self._call_interpretation_model(prompt_payload, max_tokens=max_tokens)
            warnings.extend(model_warnings)
        else:
            warnings.append("已按参数跳过模型调用；本报告只包含结构化输入摘要。")

        payload = {
            "analysis_id": f"ai_{scenario}:{datetime.now(tz=UTC).strftime('%Y%m%dT%H%M%SZ')}",
            "generated_at_beijing": iso_beijing(),
            "timezone": "Asia/Shanghai",
            "scenario": scenario,
            "target_id": target_id,
            "execution_boundary": "read_only_analysis_no_auto_order",
            "source_paths": [str(path) for path in source_paths],
            "model_status": model_status,
            "model": {
                "provider": self.settings.ai.provider,
                "model": self.settings.ai.model,
                "markdown": model_text,
            },
            "prompt_payload": prompt_payload,
            "warnings": warnings,
        }
        json_path, markdown_path = self._write_interpretation_outputs(payload)
        return AIInterpretationRunResult(
            generated_at_beijing=str(payload["generated_at_beijing"]),
            json_path=json_path,
            markdown_path=markdown_path,
            scenario=scenario,
            target_id=target_id,
            model_status=model_status,
            source_paths=source_paths,
            warnings=warnings,
        )

    def _call_interpretation_model(self, prompt_payload: dict[str, Any], *, max_tokens: int) -> tuple[str, str, list[str]]:
        config = self.settings.ai
        warnings: list[str] = []
        provider = (config.provider or "").strip().lower()
        if provider in {"", "none", "off", "disabled"}:
            return "skipped", "", ["AI provider 未启用，未调用模型。"]
        if not config.base_url:
            return "error", "", ["AI base_url 未配置，无法调用模型。"]
        if provider in {"deepseek", "openai"} and not config.api_key:
            return "error", "", ["托管 AI provider 缺少 API key，无法调用模型。"]

        client = self.client or OpenAICompatibleClient.from_ai_config(config)
        messages = [
            {
                "role": "system",
                "content": (
                    "你是 QuantPlatform 的保守美股交易辅助分析助手。"
                    "你只能基于用户给出的结构化 JSON 做解释、风险研判和人工复核建议。"
                    "你不是自动交易系统，不得输出下单、撤单、改单或自动执行指令。"
                    "如果数据不足、过期或存在 provider 限制，必须明确写出。"
                    "请用中文 Markdown 输出。"
                ),
            },
            {"role": "user", "content": json.dumps(prompt_payload, ensure_ascii=False, default=str)},
        ]
        try:
            response = client.chat(messages, temperature=0.15, max_tokens=max_tokens)
            text = extract_chat_text(response).strip()
        except Exception as exc:  # noqa: BLE001 - write an explicit failed model report instead of a fake analysis.
            return "error", "", [f"模型调用失败：{exc}"]
        if not text:
            return "error", "", ["模型返回为空，未生成 AI 解读。"]
        return "success", text, warnings

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

    def _write_interpretation_outputs(self, payload: dict[str, Any]) -> tuple[Path, Path]:
        output_dir = self.settings.storage.processed_dir.parent / "reports" / "ai_analysis"
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
        scenario = str(payload.get("scenario") or "analysis")
        target = _safe_filename(str(payload.get("target_id") or "latest"))
        json_path = output_dir / f"ai_{scenario}_{target}_{timestamp}.json"
        markdown_path = output_dir / f"ai_{scenario}_{target}_{timestamp}.md"
        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        markdown_path.write_text(_render_interpretation_markdown(payload), encoding="utf-8")
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


def _latest_report_path(directory: Path, pattern: str) -> Path:
    candidates = sorted(directory.glob(pattern))
    if not candidates:
        raise FileNotFoundError(f"没有找到结构化报告：{directory / pattern}")
    return candidates[-1]


def _read_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON report must be an object: {path}")
    return payload


def _account_health_prompt_context(payload: dict[str, Any]) -> dict[str, Any]:
    assessment = payload.get("risk_assessment") if isinstance(payload.get("risk_assessment"), dict) else {}
    account = payload.get("account") if isinstance(payload.get("account"), dict) else {}
    positions = assessment.get("positions") if isinstance(assessment.get("positions"), list) else []
    sectors = assessment.get("sector_exposures") if isinstance(assessment.get("sector_exposures"), list) else []
    return {
        "report_type": "account_health",
        "as_of": payload.get("as_of"),
        "generated_at_beijing": payload.get("generated_at_beijing"),
        "data_sources": payload.get("data_sources"),
        "account_summary": _pick(
            account,
            [
                "currency",
                "net_assets",
                "market_value",
                "total_cash",
                "available_cash",
                "buy_power",
                "total_pl",
                "total_today_pl",
                "risk_level",
                "cash_for_cash_secured_put",
                "position_count",
            ],
        ),
        "risk_summary": _pick(
            assessment,
            [
                "equity",
                "cash",
                "cash_ratio_pct",
                "invested_value",
                "position_count",
                "hhi",
                "health_score",
                "health_state",
                "pdt",
                "max_loss_checks",
                "recommendations",
                "warnings",
            ],
        ),
        "top_positions_by_weight": _limit_list(_sort_dicts_by_number(positions, "weight_pct"), 12, _compact_risk_position),
        "sector_exposures": _limit_list(_sort_dicts_by_number(sectors, "weight_pct"), 10, lambda item: item),
        "event_risks": _limit_list(assessment.get("event_risks") or [], 10, lambda item: item),
        "position_actions": _limit_list(payload.get("position_actions") or [], 10, lambda item: item),
        "improvement_plan": _limit_list(payload.get("improvement_plan") or [], 8, lambda item: item),
        "snapshot_notes": _limit_list(payload.get("snapshot_notes") or [], 10, lambda item: item),
        "analysis_requirements": [
            "用账户健康度报告解释当前组合最重要的风险。",
            "说明哪些建议只是控仓/复核建议，不是自动交易指令。",
            "指出现金、PDT、事件风险、集中度和 ATR 止损的含义。",
            "给出人工复盘优先级和需要补充确认的数据。",
        ],
    }


def _options_advice_prompt_context(payload: dict[str, Any]) -> dict[str, Any]:
    positions = payload.get("positions") if isinstance(payload.get("positions"), list) else []
    return {
        "report_type": "options_advice",
        "as_of": payload.get("as_of"),
        "generated_at_beijing": payload.get("generated_at_beijing"),
        "data_sources": payload.get("data_sources"),
        "account_summary": payload.get("account_summary"),
        "scan_policy": payload.get("scan_policy"),
        "summary": payload.get("summary"),
        "positions": _limit_list(positions, 20, _compact_options_position),
        "errors": payload.get("errors") or [],
        "analysis_requirements": [
            "解释 covered call 和 cash-secured put 建议为什么适合或不适合。",
            "重点说明现金担保、100 股要求、流动性、bid/ask 估算和 yfinance 数据限制。",
            "不要把期权候选写成下单指令；必须要求用户在券商界面人工核对合约、价格和权限。",
            "按风险优先级给出人工复核清单。",
        ],
    }


def _stock_prompt_context(
    snapshot: StockSnapshot,
    *,
    account_payload: dict[str, Any] | None,
    options_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    technical = _technical_interpretation(snapshot)
    health = _holding_health(snapshot, _matching_account_position(account_payload, snapshot.symbol), technical)
    risks = _risk_warnings(snapshot, _matching_account_position(account_payload, snapshot.symbol), technical, health)
    return {
        "report_type": "stock_technical",
        "symbol": snapshot.symbol,
        "snapshot": _compact_stock_snapshot_for_prompt(snapshot),
        "technical_interpretation": technical,
        "risk_warnings": risks,
        "matched_account_position": _matching_account_position(account_payload, snapshot.symbol),
        "matched_position_action": _matching_position_action(account_payload, snapshot.symbol),
        "matched_options_advice": _matching_options_position(options_payload, snapshot.symbol),
        "analysis_requirements": [
            "解释该股票技术面状态，包括趋势、RSI、MACD、ATR、成交量和数据新鲜度。",
            "如有真实持仓或期权建议，结合仓位、成本、风险动作做保守解读。",
            "不要给自动买卖指令；只能给观察、复核和人工决策前检查项。",
            "明确哪些结论来自本地指标，哪些因为缺数据需要谨慎。",
        ],
    }


def _build_model_prompt_payload(*, scenario: str, target_id: str, context: dict[str, Any]) -> dict[str, Any]:
    return {
        "role": "trading_assistance_analysis_not_auto_trading",
        "scenario": scenario,
        "target_id": target_id,
        "language": "zh-CN",
        "output_format": {
            "format": "markdown",
            "required_sections": [
                "一句话结论",
                "数据依据",
                "主要风险",
                "人工复盘建议",
                "不能自动执行的边界",
                "需要补充确认的问题",
            ],
        },
        "style_requirements": [
            "保守，不夸大预测能力。",
            "必须基于 JSON 字段解释，不能编造未提供的新闻、财报或实时行情。",
            "建议必须是人工复核和风险控制语言，不得写成订单或自动执行动作。",
            "遇到数据缺失、报价源限制或时间滞后时要明确提示。",
        ],
        "structured_context": context,
    }


def _compact_stock_snapshot_for_prompt(snapshot: StockSnapshot) -> dict[str, Any]:
    selected = _compact_snapshot(snapshot)
    selected.update(
        {
            "company_name": snapshot.company_name,
            "sector": snapshot.sector,
            "industry": snapshot.industry,
            "previous_close": snapshot.previous_close,
            "open_price": snapshot.open_price,
            "high_price": snapshot.high_price,
            "low_price": snapshot.low_price,
            "regular_market_price": snapshot.regular_market_price,
            "pre_market_price": snapshot.pre_market_price,
            "post_market_price": snapshot.post_market_price,
            "market_state": snapshot.market_state,
            "market_cap": snapshot.market_cap,
            "avg_dollar_volume": snapshot.avg_dollar_volume,
            "trailing_pe": snapshot.trailing_pe,
            "forward_pe": snapshot.forward_pe,
            "next_earnings_date": snapshot.next_earnings_date,
            "screening_reasons": snapshot.screening_reasons,
            "events": snapshot.events,
            "indicators": _selected_indicators(snapshot.indicators or {}),
        }
    )
    return selected


def _selected_indicators(indicators: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "sma_5",
        "sma_20",
        "sma_50",
        "sma_200",
        "ema_12",
        "ema_26",
        "macd",
        "macd_signal",
        "macd_histogram",
        "rsi_6",
        "rsi_14",
        "rsi_24",
        "rsi_14_delta_5d",
        "roc_10",
        "ret_20d_skip5",
        "ret_60d_skip5",
        "ret_120d_skip5",
        "bbands_upper",
        "bbands_middle",
        "bbands_lower",
        "atr_14",
        "volume_ratio_20",
        "volume_zscore_60",
        "trend_distance_sma50_atr14",
        "indicators_as_of",
        "indicators_provider",
    ]
    return {key: indicators.get(key) for key in keys if key in indicators}


def _compact_risk_position(item: dict[str, Any]) -> dict[str, Any]:
    return _pick(
        item,
        [
            "symbol",
            "name",
            "sector",
            "quantity",
            "cost_price",
            "current_price",
            "market_value",
            "weight_pct",
            "unrealized_pl",
            "unrealized_pl_pct",
            "atr_stop",
            "concentration_status",
            "max_loss_status",
            "flags",
        ],
    )


def _compact_options_position(item: dict[str, Any]) -> dict[str, Any]:
    result = _pick(
        item,
        [
            "symbol",
            "name",
            "quantity",
            "available_quantity",
            "cost_price",
            "underlying_price",
            "as_of",
            "scan_status",
            "skip_reason",
            "notes",
        ],
    )
    suggestions = item.get("suggestions") if isinstance(item.get("suggestions"), list) else []
    result["suggestions"] = [_compact_option_suggestion(suggestion) for suggestion in suggestions[:4] if isinstance(suggestion, dict)]
    return result


def _compact_option_suggestion(item: dict[str, Any]) -> dict[str, Any]:
    return _pick(
        item,
        [
            "strategy",
            "symbol",
            "decision",
            "reason",
            "option_type",
            "contract_symbol",
            "strike",
            "expiration",
            "bid",
            "ask",
            "mid",
            "capital_required",
            "premium_income",
            "max_loss_estimate",
            "breakeven",
            "return_on_capital_pct",
            "annualized_return_pct",
            "dte",
            "spread_pct",
            "violations",
            "warnings",
            "confirmations",
            "data_warnings",
            "required_shares",
            "available_shares",
        ],
    )


def _matching_account_position(payload: dict[str, Any] | None, symbol: str) -> dict[str, Any] | None:
    if not payload:
        return None
    assessment = payload.get("risk_assessment") if isinstance(payload.get("risk_assessment"), dict) else {}
    for item in assessment.get("positions") or []:
        if isinstance(item, dict) and _same_symbol(item.get("symbol"), symbol):
            return _compact_risk_position(item)
    return None


def _matching_position_action(payload: dict[str, Any] | None, symbol: str) -> dict[str, Any] | None:
    if not payload:
        return None
    for item in payload.get("position_actions") or []:
        if isinstance(item, dict) and _same_symbol(item.get("symbol"), symbol):
            return item
    return None


def _matching_options_position(payload: dict[str, Any] | None, symbol: str) -> dict[str, Any] | None:
    if not payload:
        return None
    for item in payload.get("positions") or []:
        if isinstance(item, dict) and _same_symbol(item.get("symbol"), symbol):
            return _compact_options_position(item)
    return None


def _account_positions_by_symbol(payload: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not payload:
        return {}
    assessment = payload.get("risk_assessment") if isinstance(payload.get("risk_assessment"), dict) else {}
    result: dict[str, dict[str, Any]] = {}
    for item in assessment.get("positions") or []:
        if not isinstance(item, dict):
            continue
        symbol = _normalize_symbol(str(item.get("symbol") or ""))
        if symbol:
            position = _compact_risk_position(item)
            position["source"] = "account_health"
            position["health_score"] = _score_from_account_risk_position(item)
            position["health_state"] = _state_from_account_risk_position(item)
            position["risk_flags"] = item.get("flags") or []
            result[symbol] = position
    return result


def _score_from_account_risk_position(item: dict[str, Any]) -> int:
    score = 70
    if item.get("concentration_status") == "breach":
        score -= 20
    if item.get("max_loss_status") == "breach":
        score -= 20
    if item.get("flags"):
        score -= min(18, len(item.get("flags") or []) * 6)
    pnl_pct = _finite_float(item.get("unrealized_pl_pct"))
    if pnl_pct is not None:
        if pnl_pct <= -8:
            score -= 10
        elif pnl_pct >= 10:
            score += 5
    return _bounded(score)


def _state_from_account_risk_position(item: dict[str, Any]) -> str:
    score = _score_from_account_risk_position(item)
    if score >= 70:
        return "健康"
    if score >= 50:
        return "观察"
    return "风险复核"


def _same_symbol(left: Any, right: str) -> bool:
    return _normalize_symbol(str(left or "")) == _normalize_symbol(right)


def _normalize_symbol(symbol: str) -> str:
    normalized = str(symbol or "").strip().upper()
    if normalized.endswith(".US"):
        normalized = normalized[:-3]
    return normalized


def _pick(payload: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    return {key: payload.get(key) for key in keys if key in payload}


def _sort_dicts_by_number(items: list[Any], key: str) -> list[dict[str, Any]]:
    dicts = [item for item in items if isinstance(item, dict)]
    return sorted(dicts, key=lambda item: _finite_float(item.get(key)) or 0.0, reverse=True)


def _limit_list(items: Any, limit: int, transform: Any) -> list[Any]:
    if not isinstance(items, list):
        return []
    return [transform(item) for item in items[:limit]]


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
            "source": portfolio_item.get("source") or "portfolio_strategy",
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


def _render_interpretation_markdown(payload: dict[str, Any]) -> str:
    scenario = str(payload.get("scenario") or "analysis")
    target_id = str(payload.get("target_id") or "latest")
    model = payload.get("model") if isinstance(payload.get("model"), dict) else {}
    model_markdown = str(model.get("markdown") or "").strip()
    prompt_payload = payload.get("prompt_payload") if isinstance(payload.get("prompt_payload"), dict) else {}
    context = prompt_payload.get("structured_context") if isinstance(prompt_payload.get("structured_context"), dict) else {}
    source_paths = payload.get("source_paths") if isinstance(payload.get("source_paths"), list) else []
    lines = [
        f"# AI 解读报告：{_scenario_label(scenario)}",
        "",
        f"- 目标：{target_id}",
        f"- 生成时间（北京）：{payload.get('generated_at_beijing')}",
        f"- 模型状态：{payload.get('model_status')}",
        f"- 模型：{model.get('provider')} / {model.get('model')}",
        "- 边界：只读分析，不自动下单、撤单或改单",
        "",
        "## 来源",
        "",
    ]
    if source_paths:
        lines.extend(f"- {path}" for path in source_paths)
    else:
        lines.append("- 未记录来源路径")

    if model_markdown:
        lines.extend(["", "## DeepSeek 解读", "", model_markdown])
    else:
        lines.extend(
            [
                "",
                "## DeepSeek 解读",
                "",
                "本次没有可用的模型解读。请查看模型状态和数据提示；系统没有用占位结论替代真实模型输出。",
            ]
        )

    warnings = payload.get("warnings") if isinstance(payload.get("warnings"), list) else []
    if warnings:
        lines.extend(["", "## 数据提示", ""])
        lines.extend(f"- {warning}" for warning in warnings)

    lines.extend(["", "## 结构化输入摘要", "", "```json"])
    lines.append(json.dumps(_preview_context(context), ensure_ascii=False, indent=2, default=str))
    lines.extend(["```", "", "## 人工复核边界", ""])
    lines.extend(
        [
            "- AI 解读只读取本地结构化 JSON，不代表实时行情或券商最终报价。",
            "- 任何观察项都必须由用户在券商界面人工确认，尤其是期权合约、bid/ask、现金占用和持仓成本。",
            "- 没有回测或规则验证支撑的观点，不能升级为交易策略。",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def _preview_context(context: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "report_type",
        "as_of",
        "generated_at_beijing",
        "data_sources",
        "account_summary",
        "risk_summary",
        "summary",
        "symbol",
        "snapshot",
        "technical_interpretation",
        "risk_warnings",
        "matched_account_position",
        "matched_position_action",
        "matched_options_advice",
        "position_actions",
        "improvement_plan",
        "errors",
    ]
    result = {key: context.get(key) for key in keys if key in context}
    if "top_positions_by_weight" in context:
        result["top_positions_by_weight"] = context["top_positions_by_weight"][:5]
    if "positions" in context:
        result["positions"] = context["positions"][:6]
    if "event_risks" in context:
        result["event_risks"] = context["event_risks"][:5]
    return result


def _scenario_label(scenario: str) -> str:
    labels = {
        "account_health": "账户健康度",
        "options_advice": "期权建议",
        "stock_technical": "个股技术面",
    }
    return labels.get(scenario, scenario)


def _safe_filename(value: str) -> str:
    safe = "".join(char if char.isalnum() or char in {"-", "_", "."} else "_" for char in value)
    return safe[:80] or "latest"


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
