"""Automated stock and options scanning reports."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from quant_platform.config import Settings
from quant_platform.portfolio import AccountSnapshot
from quant_platform.services.account import LongbridgeAccountService
from quant_platform.services.bootstrap import bootstrap_local_state
from quant_platform.services.operation_log import OperationLogger, operation_log_root
from quant_platform.time_utils import iso_beijing

if TYPE_CHECKING:
    from quant_platform.options.advice import AccountOptionsAdviceService
    from quant_platform.services.ui_data import UIDataService


@dataclass(slots=True)
class AutoScannerRunResult:
    generated_at_beijing: str
    json_path: Path
    markdown_path: Path
    pool_id: str
    stock_candidate_count: int
    covered_call_count: int
    cash_secured_put_count: int
    error_count: int


class AutoScannerService:
    """Run stock scanner and account-aware options scanner as a single report."""

    def __init__(
        self,
        settings: Settings,
        *,
        ui_data: "UIDataService | None" = None,
        account_service: LongbridgeAccountService | None = None,
        options_advice: "AccountOptionsAdviceService | None" = None,
    ) -> None:
        self.settings = settings
        self.artifacts = bootstrap_local_state(settings)
        if ui_data is None:
            from quant_platform.services.ui_data import UIDataService

            ui_data = UIDataService(settings)
        self.ui_data = ui_data
        self.account_service = account_service or LongbridgeAccountService(settings)
        if options_advice is None:
            from quant_platform.options.advice import AccountOptionsAdviceService

            options_advice = AccountOptionsAdviceService(settings, account_service=self.account_service)
        self.options_advice = options_advice
        self.logger = OperationLogger(operation_log_root(settings), "auto_scanner")

    def run(
        self,
        *,
        pool_id: str = "longbridge_core",
        as_of: date | None = None,
        min_dte: int = 14,
        max_dte: int = 45,
        max_positions: int | None = None,
        csp_watch_limit: int = 10,
    ) -> AutoScannerRunResult:
        as_of = as_of or date.today()
        self.logger.info("auto_scanner.run.start", pool_id=pool_id, as_of=as_of.isoformat())
        errors: list[dict[str, str]] = []
        try:
            stock_scan = self.ui_data.scanner(pool_id)
        except Exception as exc:  # noqa: BLE001 - write a report showing scanner failure.
            errors.append({"source": "stock_scanner", "error": str(exc)})
            stock_scan = {"summary": {}, "candidates": [], "pool": {"pool_id": pool_id}}
            self.logger.error("auto_scanner.stock.error", pool_id=pool_id, error=str(exc))

        account: AccountSnapshot | None = None
        try:
            account = self.account_service.snapshot(currency="USD")
        except Exception as exc:  # noqa: BLE001 - options scan can degrade without account data.
            errors.append({"source": "account", "error": str(exc)})
            self.logger.error("auto_scanner.account.error", error=str(exc))

        options_payload: dict[str, Any] = {
            "covered_call": [],
            "cash_secured_put": [],
            "cash_secured_put_watchlist": [],
            "source_report": None,
        }
        if account is not None:
            try:
                advice_result = self.options_advice.generate(
                    as_of=as_of,
                    min_dte=min_dte,
                    max_dte=max_dte,
                    max_positions=max_positions,
                )
                advice_payload = json.loads(advice_result.json_path.read_text(encoding="utf-8"))
                options_payload.update(_extract_options_scan(advice_payload))
                options_payload["source_report"] = {
                    "json_path": str(advice_result.json_path),
                    "markdown_path": str(advice_result.markdown_path),
                }
            except Exception as exc:  # noqa: BLE001 - stock scan should still be useful.
                errors.append({"source": "options_advice", "error": str(exc)})
                self.logger.error("auto_scanner.options.error", error=str(exc))
            options_payload["cash_secured_put_watchlist"] = _csp_watchlist_candidates(
                stock_scan.get("candidates") if isinstance(stock_scan.get("candidates"), list) else [],
                account=account,
                limit=csp_watch_limit,
            )

        payload = {
            "analysis_id": f"auto_scanner:{datetime.now(tz=UTC).strftime('%Y%m%dT%H%M%SZ')}",
            "generated_at_beijing": iso_beijing(),
            "timezone": "Asia/Shanghai",
            "as_of": as_of.isoformat(),
            "pool_id": pool_id,
            "execution_boundary": "read_only_analysis_no_auto_order",
            "stock_scan": stock_scan,
            "options_scan": options_payload,
            "errors": errors,
            "schedule_note": "可由 make auto-scan 或外部 launchd/crontab 定时调用；脚本本身不执行交易。",
        }
        json_path, markdown_path = self._write_outputs(payload)
        stock_count = len(stock_scan.get("candidates", [])) if isinstance(stock_scan.get("candidates"), list) else 0
        cc_count = len(options_payload.get("covered_call") or [])
        csp_count = len(options_payload.get("cash_secured_put") or []) + len(options_payload.get("cash_secured_put_watchlist") or [])
        self.logger.info(
            "auto_scanner.run.success",
            pool_id=pool_id,
            json_path=str(json_path),
            markdown_path=str(markdown_path),
            stock_candidates=stock_count,
            covered_call=cc_count,
            cash_secured_put=csp_count,
            errors=len(errors),
        )
        return AutoScannerRunResult(
            generated_at_beijing=str(payload["generated_at_beijing"]),
            json_path=json_path,
            markdown_path=markdown_path,
            pool_id=pool_id,
            stock_candidate_count=stock_count,
            covered_call_count=cc_count,
            cash_secured_put_count=csp_count,
            error_count=len(errors),
        )

    def _write_outputs(self, payload: dict[str, Any]) -> tuple[Path, Path]:
        output_dir = self.settings.storage.processed_dir.parent / "reports" / "scanner"
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
        json_path = output_dir / f"auto_scan_{payload.get('pool_id')}_{timestamp}.json"
        markdown_path = output_dir / f"auto_scan_{payload.get('pool_id')}_{timestamp}.md"
        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        markdown_path.write_text(_render_markdown(payload), encoding="utf-8")
        return json_path, markdown_path


def _extract_options_scan(payload: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    covered_call: list[dict[str, Any]] = []
    cash_secured_put: list[dict[str, Any]] = []
    for position in payload.get("positions") or []:
        if not isinstance(position, dict):
            continue
        for suggestion in position.get("suggestions") or []:
            if not isinstance(suggestion, dict):
                continue
            item = {
                "symbol": position.get("symbol"),
                "decision": suggestion.get("decision"),
                "strategy": suggestion.get("strategy"),
                "strike": suggestion.get("strike"),
                "expiration": suggestion.get("expiration"),
                "dte": suggestion.get("dte"),
                "premium_income": suggestion.get("premium_income"),
                "annualized_return_pct": suggestion.get("annualized_return_pct"),
                "warnings": suggestion.get("warnings") or suggestion.get("data_warnings") or [],
            }
            if suggestion.get("strategy") == "covered_call":
                covered_call.append(item)
            if suggestion.get("strategy") == "cash_secured_put":
                cash_secured_put.append(item)
    return {"covered_call": covered_call, "cash_secured_put": cash_secured_put}


def _csp_watchlist_candidates(candidates: list[Any], *, account: AccountSnapshot, limit: int) -> list[dict[str, Any]]:
    cash = account.cash_for_cash_secured_put
    max_cash = cash * 0.4
    held = {position.internal_symbol for position in account.positions}
    result: list[dict[str, Any]] = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol") or "").upper()
        price = _float(item.get("price"))
        if not symbol or symbol in held or price is None or price <= 0:
            continue
        if item.get("risk_level") == "高" or item.get("action") not in {"候选买入", "继续观察"}:
            continue
        cash_required = price * 0.9 * 100
        if cash_required > max_cash:
            continue
        result.append(
            {
                "symbol": symbol,
                "strategy": "cash_secured_put",
                "decision": "继续观察",
                "underlying_price": round(price, 2),
                "estimated_90pct_strike_cash_required": round(cash_required, 2),
                "scanner_score": item.get("score"),
                "scanner_action": item.get("action"),
                "warnings": ["未拉取具体期权链，需在期权建议报告或券商界面继续验证 bid/ask、DTE、OI 和财报风险。"],
            }
        )
        if len(result) >= limit:
            break
    return result


def _render_markdown(payload: dict[str, Any]) -> str:
    stock_scan = payload.get("stock_scan") if isinstance(payload.get("stock_scan"), dict) else {}
    options = payload.get("options_scan") if isinstance(payload.get("options_scan"), dict) else {}
    summary = stock_scan.get("summary") if isinstance(stock_scan.get("summary"), dict) else {}
    candidates = [item for item in stock_scan.get("candidates", []) if isinstance(item, dict)]
    lines = [
        "# 自动扫描报告",
        "",
        f"- 生成时间（北京）：{payload.get('generated_at_beijing')}",
        f"- 分析日期：{payload.get('as_of')}",
        f"- 股票池：{payload.get('pool_id')}",
        "- 边界：只读扫描，不自动下单、撤单或改单",
        "",
        "## 股票扫描",
        "",
        f"- 候选买入：{summary.get('candidate_buy', 0)}，继续观察：{summary.get('watch', 0)}，风险回避：{summary.get('risk_avoid', 0)}，数据不足：{summary.get('insufficient_data', 0)}",
        "",
        "| 标的 | 分数 | 动作 | 风险 | 动量排名 | 日期 |",
        "| --- | ---: | --- | --- | ---: | --- |",
    ]
    for item in candidates[:20]:
        lines.append(
            f"| {item.get('symbol')} | {item.get('score')} | {item.get('action')} | {item.get('risk_level')} | "
            f"{item.get('momentum_rank_pct') if item.get('momentum_rank_pct') is not None else '-'} | {item.get('latest_history_date_us') or '-'} |"
        )
    lines.extend(["", "## 期权扫描", "", "### Covered Call", "", "| 标的 | 决策 | Strike | 到期 | 年化 | 风险提示 |", "| --- | --- | ---: | --- | ---: | --- |"])
    for item in options.get("covered_call") or []:
        lines.append(
            f"| {item.get('symbol')} | {item.get('decision')} | {item.get('strike') or '-'} | {item.get('expiration') or '-'} | "
            f"{item.get('annualized_return_pct') or '-'} | {'；'.join(item.get('warnings') or []) or '-'} |"
        )
    lines.extend(["", "### Cash-Secured Put", "", "| 标的 | 来源 | 决策 | Strike/估算 | 到期 | 提示 |", "| --- | --- | --- | ---: | --- | --- |"])
    for item in options.get("cash_secured_put") or []:
        lines.append(
            f"| {item.get('symbol')} | 期权链 | {item.get('decision')} | {item.get('strike') or '-'} | {item.get('expiration') or '-'} | "
            f"{'；'.join(item.get('warnings') or []) or '-'} |"
        )
    for item in options.get("cash_secured_put_watchlist") or []:
        lines.append(
            f"| {item.get('symbol')} | 股票扫描 | {item.get('decision')} | {item.get('estimated_90pct_strike_cash_required') or '-'} | - | "
            f"{'；'.join(item.get('warnings') or []) or '-'} |"
        )
    if payload.get("errors"):
        lines.extend(["", "## 异常", ""])
        for error in payload.get("errors") or []:
            lines.append(f"- {error.get('source')}: {error.get('error')}")
    lines.extend(["", "## 定时运行", "", f"- {payload.get('schedule_note')}"])
    return "\n".join(lines).rstrip() + "\n"


def _float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
