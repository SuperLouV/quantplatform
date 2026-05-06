"""Decision-panel AI chat backed by local structured artifacts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from quant_platform.clients.openai_compatible import OpenAICompatibleClient, extract_chat_text
from quant_platform.config import Settings
from quant_platform.services.bootstrap import bootstrap_local_state
from quant_platform.services.operation_log import OperationLogger, operation_log_root
from quant_platform.time_utils import iso_beijing


@dataclass(slots=True)
class DecisionChatResult:
    generated_at_beijing: str
    model_status: str
    answer_markdown: str
    warnings: list[str]
    source_paths: list[Path]


class DecisionChatService:
    """Answer stock and option questions using only local reports.

    This service deliberately avoids live broker actions. It reads the latest
    daily report, scanner output, account health, options advice, macro risk,
    and AI interpretation reports, then asks the configured model to explain
    the situation conservatively.
    """

    def __init__(self, settings: Settings, client: OpenAICompatibleClient | None = None) -> None:
        self.settings = settings
        self.artifacts = bootstrap_local_state(settings)
        self.client = client
        self.logger = OperationLogger(operation_log_root(settings), "decision_chat")

    def ask(
        self,
        question: str,
        *,
        symbol: str | None = None,
        history: list[dict[str, str]] | None = None,
    ) -> DecisionChatResult:
        cleaned_question = str(question or "").strip()
        if not cleaned_question:
            raise ValueError("question is required.")
        if len(cleaned_question) > 2000:
            raise ValueError("question is too long; keep it under 2000 characters.")
        normalized_symbol = str(symbol or "").upper().replace(".US", "").strip() or None
        context, source_paths, warnings = self._build_context(symbol=normalized_symbol)
        self.logger.info(
            "decision_chat.ask.start",
            symbol=normalized_symbol,
            sources=len(source_paths),
            question_chars=len(cleaned_question),
        )
        model_status, answer, model_warnings = self._call_model(
            question=cleaned_question,
            context=context,
            history=_sanitize_history(history or []),
        )
        warnings.extend(model_warnings)
        result = DecisionChatResult(
            generated_at_beijing=iso_beijing(),
            model_status=model_status,
            answer_markdown=answer,
            warnings=warnings,
            source_paths=source_paths,
        )
        self.logger.info(
            "decision_chat.ask.done",
            symbol=normalized_symbol,
            model_status=model_status,
            warnings=len(warnings),
            sources=len(source_paths),
        )
        return result

    def _build_context(self, *, symbol: str | None) -> tuple[dict[str, Any], list[Path], list[str]]:
        reports_dir = self.settings.storage.processed_dir.parent / "reports"
        reference_dir = self.settings.storage.reference_dir
        warnings: list[str] = []
        source_paths: list[Path] = []
        context: dict[str, Any] = {
            "generated_at_beijing": iso_beijing(),
            "execution_boundary": "read_only_analysis_no_auto_order",
            "requested_symbol": symbol,
            "daily_report_structured": self._load_latest_json(reports_dir, "daily*.json", source_paths, warnings),
            "daily_report": self._load_latest_markdown(reports_dir, "daily*.md", source_paths, warnings, max_chars=12000),
            "scanner": self._load_latest_json(reference_dir / "system" / "scan_results", "*.json", source_paths, warnings),
            "account_health": self._load_latest_json(reports_dir / "account_health", "account_health_*.json", source_paths, warnings),
            "options_advice": self._load_latest_json(reports_dir / "options_advice", "options_advice_*.json", source_paths, warnings),
            "macro_risk": self._load_latest_json(reports_dir / "macro_risk", "macro_risk_*.json", source_paths, warnings),
            "ai_interpretation": self._load_latest_markdown(
                reports_dir / "ai_analysis",
                "ai*.md",
                source_paths,
                warnings,
                max_chars=8000,
            ),
            "symbol_snapshot": self._load_symbol_snapshot(symbol, source_paths, warnings) if symbol else None,
        }
        context["artifact_summary"] = {
            "source_count": len(source_paths),
            "missing_or_failed": warnings,
        }
        return _compact_context(context), source_paths, warnings

    def _call_model(
        self,
        *,
        question: str,
        context: dict[str, Any],
        history: list[dict[str, str]],
    ) -> tuple[str, str, list[str]]:
        config = self.settings.ai
        provider = (config.provider or "").strip().lower()
        if provider in {"", "none", "off", "disabled"}:
            return "skipped", "", ["AI provider 未启用，无法生成对话回答。"]
        if not config.base_url:
            return "error", "", ["AI base_url 未配置，无法生成对话回答。"]
        if provider in {"deepseek", "openai"} and not config.api_key:
            return "error", "", ["托管 AI provider 缺少 API key，无法生成对话回答。"]

        messages: list[dict[str, str]] = [
            {
                "role": "system",
                "content": (
                    "你是 QuantPlatform 决策面板里的保守股票和期权交易辅助助手。"
                    "你只能基于系统提供的本地结构化产物回答，不能编造未给出的实时行情、新闻或账户数据。"
                    "你不得输出真实下单、撤单、改单、自动执行或替用户决策的指令。"
                    "回答必须使用中文 Markdown，包含数据依据、风险、人工复核事项和数据缺口。"
                ),
            }
        ]
        messages.extend(history[-6:])
        messages.append(
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "question": question,
                        "local_context": context,
                        "required_boundary": "manual_review_only_no_auto_order",
                    },
                    ensure_ascii=False,
                    default=str,
                ),
            }
        )
        client = self.client or OpenAICompatibleClient.from_ai_config(config)
        try:
            response = client.chat(messages, temperature=0.15, max_tokens=1800)
            text = extract_chat_text(response).strip()
        except Exception as exc:  # noqa: BLE001 - UI should show explicit model failure.
            return "error", "", [f"模型调用失败：{exc}"]
        if not text:
            return "error", "", ["模型返回为空，未生成回答。"]
        return "success", text, []

    def _load_latest_json(
        self,
        directory: Path,
        pattern: str,
        source_paths: list[Path],
        warnings: list[str],
    ) -> dict[str, Any] | None:
        path = _latest_file(directory, pattern)
        if path is None:
            warnings.append(f"缺少本地 JSON 产物：{directory / pattern}")
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            warnings.append(f"读取 JSON 产物失败：{path}，{exc}")
            return None
        source_paths.append(path)
        return payload if isinstance(payload, dict) else {"value": payload}

    def _load_latest_markdown(
        self,
        directory: Path,
        pattern: str,
        source_paths: list[Path],
        warnings: list[str],
        *,
        max_chars: int,
    ) -> dict[str, Any] | None:
        path = _latest_file(directory, pattern)
        if path is None:
            warnings.append(f"缺少本地 Markdown 产物：{directory / pattern}")
            return None
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            warnings.append(f"读取 Markdown 产物失败：{path}，{exc}")
            return None
        source_paths.append(path)
        return {
            "path": str(path),
            "updated_at": datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).isoformat(),
            "content_excerpt": text[:max_chars],
            "truncated": len(text) > max_chars,
        }

    def _load_symbol_snapshot(self, symbol: str | None, source_paths: list[Path], warnings: list[str]) -> dict[str, Any] | None:
        if not symbol:
            return None
        path = self.settings.storage.processed_dir / "snapshots" / f"{symbol}.json"
        if not path.exists():
            warnings.append(f"缺少 {symbol} 本地快照。")
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            warnings.append(f"读取 {symbol} 快照失败：{exc}")
            return None
        source_paths.append(path)
        return payload if isinstance(payload, dict) else None


def _compact_context(context: dict[str, Any]) -> dict[str, Any]:
    compact = dict(context)
    scanner = compact.get("scanner")
    if isinstance(scanner, dict):
        candidates = scanner.get("candidates") if isinstance(scanner.get("candidates"), list) else []
        compact["scanner"] = {
            "generated_at": scanner.get("generated_at"),
            "market_date_us": scanner.get("market_date_us"),
            "pool": scanner.get("pool"),
            "summary": scanner.get("summary"),
            "top_candidates": candidates[:12],
        }
    daily_structured = compact.get("daily_report_structured")
    if isinstance(daily_structured, dict):
        compact["daily_report_structured"] = {
            "schema_version": daily_structured.get("schema_version"),
            "report_metadata": daily_structured.get("report_metadata"),
            "executive_summary": daily_structured.get("executive_summary"),
            "market_context": daily_structured.get("market_context"),
            "top_holdings_analysis": (daily_structured.get("holdings_analysis") or [])[:12]
            if isinstance(daily_structured.get("holdings_analysis"), list)
            else [],
            "watchlist_monitor": (daily_structured.get("watchlist_monitor") or [])[:12]
            if isinstance(daily_structured.get("watchlist_monitor"), list)
            else [],
            "options_strategy_advice": daily_structured.get("options_strategy_advice"),
            "data_gaps": (daily_structured.get("data_gaps") or [])[:20] if isinstance(daily_structured.get("data_gaps"), list) else [],
        }
    account = compact.get("account_health")
    if isinstance(account, dict):
        assessment = account.get("risk_assessment") if isinstance(account.get("risk_assessment"), dict) else {}
        compact["account_health"] = {
            "generated_at_beijing": account.get("generated_at_beijing"),
            "as_of": account.get("as_of"),
            "account": account.get("account"),
            "risk_summary": {
                key: assessment.get(key)
                for key in (
                    "equity",
                    "cash",
                    "cash_ratio_pct",
                    "position_count",
                    "hhi",
                    "health_score",
                    "health_state",
                    "pdt",
                    "recommendations",
                    "warnings",
                )
            },
            "positions": (assessment.get("positions") or [])[:12] if isinstance(assessment.get("positions"), list) else [],
            "position_actions": (account.get("position_actions") or [])[:12] if isinstance(account.get("position_actions"), list) else [],
        }
    options = compact.get("options_advice")
    if isinstance(options, dict):
        compact["options_advice"] = {
            "generated_at_beijing": options.get("generated_at_beijing"),
            "as_of": options.get("as_of"),
            "account_summary": options.get("account_summary"),
            "summary": options.get("summary"),
            "positions": (options.get("positions") or [])[:12] if isinstance(options.get("positions"), list) else [],
            "errors": options.get("errors") or [],
        }
    macro = compact.get("macro_risk")
    if isinstance(macro, dict):
        overview = macro.get("market_overview") if isinstance(macro.get("market_overview"), dict) else {}
        compact["macro_risk"] = {
            "generated_at_beijing": macro.get("generated_at_beijing"),
            "market_date_us": macro.get("market_date_us"),
            "risk_state": macro.get("risk_state"),
            "sentiment_state": macro.get("sentiment_state"),
            "scanner_filter_hint": macro.get("scanner_filter_hint"),
            "market_overview_summary": overview.get("summary") if isinstance(overview, dict) else None,
            "news_items": (macro.get("news_items") or [])[:20] if isinstance(macro.get("news_items"), list) else [],
            "warnings": macro.get("warnings") or [],
        }
    return compact


def _sanitize_history(items: list[dict[str, str]]) -> list[dict[str, str]]:
    sanitized: list[dict[str, str]] = []
    for item in items[-8:]:
        role = str(item.get("role") or "").strip()
        content = str(item.get("content") or "").strip()
        if role not in {"user", "assistant"} or not content:
            continue
        sanitized.append({"role": role, "content": content[:1500]})
    return sanitized


def _latest_file(directory: Path, pattern: str) -> Path | None:
    candidates = sorted(directory.glob(pattern))
    return candidates[-1] if candidates else None
