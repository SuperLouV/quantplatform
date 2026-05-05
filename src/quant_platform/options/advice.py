"""Account-aware simple options advice using read-only positions and yfinance."""

from __future__ import annotations

import json
import math
import sys
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError, as_completed
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal

from quant_platform.clients.yfinance import YFinanceClient
from quant_platform.config import Settings
from quant_platform.options.models import AccountProfile, OptionContract, OptionEvaluation, OptionStrategyRequest, StockOptionContext
from quant_platform.options.strategies import evaluate_cash_secured_put, evaluate_covered_call
from quant_platform.portfolio import AccountPosition
from quant_platform.services.account import LongbridgeAccountService
from quant_platform.time_utils import iso_beijing

StrategyName = Literal["covered_call", "cash_secured_put"]

PRIMARY_OPTION_UNDERLYINGS = {"AAPL", "TSLA", "NVDA", "GOOGL", "GOOG", "TSM"}
SECONDARY_OPTION_UNDERLYINGS = {"VOO", "QQQ", "EWT", "EWJ", "DRAM", "BRK.B"}
OPTION_SCAN_SKIP_REASONS = {
    "VOO": "ETF 期权扫描放到 secondary，避免拖慢默认报告。",
    "QQQ": "ETF 期权扫描放到 secondary，避免拖慢默认报告。",
    "EWT": "ETF 期权扫描放到 secondary，避免拖慢默认报告。",
    "EWJ": "ETF 期权扫描放到 secondary，避免拖慢默认报告。",
    "DRAM": "ETF/主题基金期权扫描放到 secondary，避免拖慢默认报告。",
    "BRK.B": "BRK.B 期权链较重且不是默认 covered-call/CSP 优先标的。",
}


@dataclass(slots=True)
class OptionsAdviceRunResult:
    generated_at_beijing: str
    json_path: Path
    markdown_path: Path
    position_count: int
    advice_count: int
    error_count: int


class AccountOptionsAdviceService:
    """Generate covered call and cash-secured put ideas for real holdings.

    This service is intentionally read-only. It reads positions from Longbridge,
    reads option chains from yfinance, then writes research reports only.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        account_service: LongbridgeAccountService | None = None,
        yfinance_client: YFinanceClient | None = None,
    ) -> None:
        self.settings = settings
        self.account_service = account_service or LongbridgeAccountService(settings)
        self.yfinance = yfinance_client or YFinanceClient.from_data_config(settings.data)

    def generate(
        self,
        *,
        as_of: date | None = None,
        min_dte: int = 14,
        max_dte: int = 45,
        max_positions: int | None = None,
        max_workers: int = 2,
        timeout_seconds: float = 60.0,
        max_expirations_per_symbol: int = 2,
    ) -> OptionsAdviceRunResult:
        as_of = as_of or date.today()
        account = self.account_service.snapshot(currency="USD")
        positions = [position for position in account.positions if _is_us_stock_position(position)]
        if max_positions is not None:
            positions = positions[:max_positions]

        items: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        scan_positions: list[AccountPosition] = []
        for position in positions:
            skip_reason = _default_skip_reason(position.internal_symbol)
            if skip_reason:
                items.append(_skipped_position_item(position, as_of=as_of, reason=skip_reason))
                _print_progress(f"skip {position.internal_symbol}: {skip_reason}")
                continue
            scan_positions.append(position)

        deadline = time.monotonic() + timeout_seconds
        max_workers = max(1, max_workers)
        if scan_positions:
            _print_progress(
                f"scan {len(scan_positions)} active option underlyings with max_workers={max_workers}, "
                f"timeout={timeout_seconds:.0f}s, expirations_per_symbol={max_expirations_per_symbol}"
            )
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_by_symbol = {
                executor.submit(
                    self._position_advice,
                    position,
                    account_profile=account.to_options_account(position.internal_symbol),
                    as_of=as_of,
                    min_dte=min_dte,
                    max_dte=max_dte,
                    max_expirations_per_symbol=max_expirations_per_symbol,
                ): position.internal_symbol
                for position in scan_positions
                if time.monotonic() < deadline
            }
            completed = 0
            try:
                for future in as_completed(future_by_symbol, timeout=max(0.1, deadline - time.monotonic())):
                    symbol = future_by_symbol[future]
                    completed += 1
                    try:
                        items.append(future.result(timeout=max(0.1, deadline - time.monotonic())))
                        _print_progress(f"done {symbol} ({completed}/{len(future_by_symbol)})")
                    except Exception as exc:  # noqa: BLE001 - one symbol failure must not break the account report.
                        errors.append({"symbol": symbol, "error": str(exc)})
                        _print_progress(f"error {symbol}: {exc}")
            except TimeoutError:
                pending = sorted(symbol for future, symbol in future_by_symbol.items() if not future.done())
                for symbol in pending:
                    errors.append({"symbol": symbol, "error": f"options scan timed out after {timeout_seconds:.0f}s"})
                _print_progress(f"timeout pending={', '.join(pending) if pending else '-'}")

        payload = {
            "analysis_id": f"options_advice:{datetime.now(tz=UTC).strftime('%Y%m%dT%H%M%SZ')}",
            "generated_at_beijing": iso_beijing(),
            "timezone": "Asia/Shanghai",
            "as_of": as_of.isoformat(),
            "execution_boundary": "read_only_analysis_no_auto_order",
            "data_sources": {
                "positions": account.provider,
                "options": "yfinance",
            },
            "account_summary": {
                "currency": account.currency,
                "equity_for_risk": round(account.equity_for_risk, 2),
                "cash_for_cash_secured_put": round(account.cash_for_cash_secured_put, 2),
                "position_count": len(positions),
                "risk_level": account.risk_level,
            },
            "scan_policy": {
                "primary_underlyings": sorted(PRIMARY_OPTION_UNDERLYINGS),
                "secondary_underlyings": sorted(SECONDARY_OPTION_UNDERLYINGS),
                "max_workers": max_workers,
                "timeout_seconds": timeout_seconds,
                "max_expirations_per_symbol": max_expirations_per_symbol,
            },
            "summary": _summarize_items(items, errors),
            "positions": items,
            "errors": errors,
        }
        json_path, markdown_path = _write_outputs(self.settings, payload)
        return OptionsAdviceRunResult(
            generated_at_beijing=str(payload["generated_at_beijing"]),
            json_path=json_path,
            markdown_path=markdown_path,
            position_count=len(positions),
            advice_count=sum(len(item.get("suggestions") or []) for item in items),
            error_count=len(errors),
        )

    def _position_advice(
        self,
        position: AccountPosition,
        *,
        account_profile: AccountProfile,
        as_of: date,
        min_dte: int,
        max_dte: int,
        max_expirations_per_symbol: int,
    ) -> dict[str, Any]:
        symbol = position.internal_symbol
        _print_progress(f"fetch {symbol}: quote and expirations")
        quote = self.yfinance.fetch_quote_snapshot(symbol)
        underlying_price = _first_float(position.market_price, quote.get("current_price"), quote.get("regular_market_price"), quote.get("latest_close"))
        if underlying_price is None:
            raise ValueError("无法获取正股价格。")

        expirations = [
            expiration
            for expiration in self.yfinance.fetch_option_expirations(symbol)
            if min_dte <= (expiration - as_of).days <= max_dte
        ][:max_expirations_per_symbol]
        _print_progress(f"fetch {symbol}: {len(expirations)} option chains")
        chains = {expiration: self.yfinance.fetch_option_chain(symbol, expiration) for expiration in expirations}
        stock = StockOptionContext(
            symbol=symbol,
            current_price=underlying_price,
            as_of=as_of,
            support_price=_support_price(underlying_price),
            resistance_price=_resistance_price(underlying_price),
            earnings_days=_days_until(date.fromisoformat(quote["next_earnings_date"]), as_of) if quote.get("next_earnings_date") else None,
        )
        suggestions = [
            suggestion
            for suggestion in [
                self._best_covered_call(symbol, stock, position, account_profile, chains),
                self._best_cash_secured_put(symbol, stock, account_profile, chains),
            ]
            if suggestion is not None
        ]
        return {
            "symbol": symbol,
            "name": position.name,
            "quantity": position.quantity,
            "available_quantity": position.available_quantity,
            "cost_price": position.cost_price,
            "underlying_price": round(underlying_price, 2),
            "as_of": as_of.isoformat(),
            "suggestions": suggestions,
            "notes": _position_notes(position, suggestions),
        }

    def _best_covered_call(
        self,
        symbol: str,
        stock: StockOptionContext,
        position: AccountPosition,
        account: AccountProfile,
        chains: dict[date, dict[str, list[dict[str, Any]]]],
    ) -> dict[str, Any] | None:
        if position.available_quantity < 100:
            return {
                "strategy": "covered_call",
                "decision": "不适合",
                "reason": "Covered call 需要至少 100 股可用正股。",
                "required_shares": 100,
                "available_shares": position.available_quantity,
            }
        rows = []
        min_strike = max(stock.current_price * 1.03, position.cost_price or 0)
        for expiration, chain in chains.items():
            for row in chain.get("calls", []):
                strike = _optional_float(row.get("strike"))
                if strike is None or strike < min_strike:
                    continue
                rows.append((expiration, row))
        return self._best_evaluation(
            strategy="covered_call",
            symbol=symbol,
            stock=stock,
            account=account,
            rows=rows,
        )

    def _best_cash_secured_put(
        self,
        symbol: str,
        stock: StockOptionContext,
        account: AccountProfile,
        chains: dict[date, dict[str, list[dict[str, Any]]]],
    ) -> dict[str, Any] | None:
        rows = []
        max_strike = stock.current_price * 0.95
        min_strike = stock.current_price * 0.75
        for expiration, chain in chains.items():
            for row in chain.get("puts", []):
                strike = _optional_float(row.get("strike"))
                if strike is None or strike > max_strike or strike < min_strike:
                    continue
                rows.append((expiration, row))
        return self._best_evaluation(
            strategy="cash_secured_put",
            symbol=symbol,
            stock=stock,
            account=account,
            rows=rows,
        )

    def _best_evaluation(
        self,
        *,
        strategy: StrategyName,
        symbol: str,
        stock: StockOptionContext,
        account: AccountProfile,
        rows: list[tuple[date, dict[str, Any]]],
    ) -> dict[str, Any] | None:
        evaluations: list[tuple[OptionEvaluation, dict[str, Any], list[str]]] = []
        for expiration, row in rows:
            contract, warnings = _contract_from_row(symbol, strategy, expiration, row)
            request = OptionStrategyRequest(strategy=strategy, account=account, stock=stock, contract=contract)
            evaluation = evaluate_covered_call(request) if strategy == "covered_call" else evaluate_cash_secured_put(request)
            if warnings:
                evaluation.warnings.extend(warnings)
            evaluations.append((evaluation, row, warnings))
        if not evaluations:
            return {
                "strategy": strategy,
                "decision": "继续观察",
                "reason": "yfinance 期权链中没有符合第一版 DTE/OTM 条件的合约。",
            }
        evaluations.sort(key=lambda item: _evaluation_sort_key(item[0]))
        best, row, data_warnings = evaluations[0]
        payload = best.to_dict()
        payload.update(
            {
                "strategy": strategy,
                "option_type": "call" if strategy == "covered_call" else "put",
                "contract_symbol": row.get("contract_symbol"),
                "strike": payload["ai_context"]["request"]["contract"]["strike"],
                "expiration": payload["ai_context"]["request"]["contract"]["expiration"],
                "bid": payload["ai_context"]["request"]["contract"]["bid"],
                "ask": payload["ai_context"]["request"]["contract"]["ask"],
                "mid": payload["ai_context"]["request"]["contract"]["mid"],
                "data_warnings": data_warnings,
            }
        )
        return payload


def _contract_from_row(
    symbol: str,
    strategy: StrategyName,
    expiration: date,
    row: dict[str, Any],
) -> tuple[OptionContract, list[str]]:
    option_type = "call" if strategy == "covered_call" else "put"
    bid = _optional_float(row.get("bid")) or 0.0
    ask = _optional_float(row.get("ask")) or 0.0
    warnings: list[str] = []
    last_price = _optional_float(row.get("last_price"))
    if bid <= 0 and ask <= 0 and last_price is not None and last_price > 0:
        bid = last_price
        ask = last_price
        warnings.append("yfinance bid/ask 为空，临时使用 last price 估算权利金。")
    return (
        OptionContract(
            symbol=symbol,
            option_type=option_type,  # type: ignore[arg-type]
            strike=float(row["strike"]),
            expiration=expiration,
            bid=bid,
            ask=ask,
            implied_volatility=_optional_float(row.get("implied_volatility")),
            volume=_optional_int(row.get("volume")),
            open_interest=_optional_int(row.get("open_interest")),
        ),
        warnings,
    )


def _evaluation_sort_key(evaluation: OptionEvaluation) -> tuple[int, int, int, float]:
    decision_rank = {"符合策略": 0, "继续观察": 1, "不适合": 2}.get(evaluation.decision, 9)
    annualized = evaluation.annualized_return_pct or 0
    return (decision_rank, len(evaluation.violations), len(evaluation.warnings), -annualized)


def _summarize_items(items: list[dict[str, Any]], errors: list[dict[str, str]]) -> dict[str, Any]:
    decisions: dict[str, int] = {}
    strategies: dict[str, int] = {}
    skipped = 0
    for item in items:
        if item.get("scan_status") == "skipped":
            skipped += 1
        for suggestion in item.get("suggestions") or []:
            if not isinstance(suggestion, dict):
                continue
            decision = str(suggestion.get("decision") or "未知")
            strategy = str(suggestion.get("strategy") or "unknown")
            decisions[decision] = decisions.get(decision, 0) + 1
            strategies[strategy] = strategies.get(strategy, 0) + 1
    return {
        "position_count": len(items),
        "suggestion_count": sum(len(item.get("suggestions") or []) for item in items),
        "decision_counts": decisions,
        "strategy_counts": strategies,
        "skipped_count": skipped,
        "error_count": len(errors),
    }


def _write_outputs(settings: Settings, payload: dict[str, Any]) -> tuple[Path, Path]:
    output_dir = settings.storage.processed_dir.parent / "reports" / "options_advice"
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
    json_path = output_dir / f"options_advice_{timestamp}.json"
    markdown_path = output_dir / f"options_advice_{timestamp}.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    markdown_path.write_text(_render_markdown(payload), encoding="utf-8")
    return json_path, markdown_path


def _render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# 期权策略建议",
        "",
        f"- 生成时间（北京）：{payload.get('generated_at_beijing')}",
        f"- 分析日期：{payload.get('as_of')}",
        "- 数据源：Longbridge 只读持仓 / yfinance 期权链",
        "- 边界：只读分析，不自动下单、撤单或改单",
        "",
        "## 总览",
        "",
        f"- 账户摘要：{payload.get('account_summary')}",
        f"- 建议统计：{payload.get('summary')}",
        f"- 扫描策略：{payload.get('scan_policy')}",
        "",
        "## 持仓建议",
        "",
    ]
    for item in payload.get("positions", []):
        lines.extend(
            [
                f"### {item.get('symbol')}",
                "",
                f"- 持仓：{item.get('quantity')} 股，可用 {item.get('available_quantity')} 股，成本 {item.get('cost_price')}，正股价 {item.get('underlying_price')}",
            ]
        )
        if item.get("scan_status") == "skipped":
            lines.append(f"- 扫描状态：跳过，原因：{item.get('skip_reason')}")
        for suggestion in item.get("suggestions") or []:
            if "strike" in suggestion:
                lines.append(
                    "- {strategy}：{decision}，strike {strike}，到期 {expiration}，"
                    "mid {mid}，权利金 ${premium}，年化 {annualized}%".format(
                        strategy=suggestion.get("strategy"),
                        decision=suggestion.get("decision"),
                        strike=suggestion.get("strike"),
                        expiration=suggestion.get("expiration"),
                        mid=suggestion.get("mid"),
                        premium=suggestion.get("premium_income"),
                        annualized=suggestion.get("annualized_return_pct"),
                    )
                )
            else:
                lines.append(f"- {suggestion.get('strategy')}：{suggestion.get('decision')}，{suggestion.get('reason')}")
        for note in item.get("notes") or []:
            lines.append(f"- 提示：{note}")
        lines.append("")
    if payload.get("errors"):
        lines.extend(["## 异常", ""])
        for error in payload.get("errors", []):
            lines.append(f"- {error.get('symbol')}: {error.get('error')}")
    lines.extend(
        [
            "",
            "## 复核边界",
            "",
            "- Covered call 和 cash-secured put 只做第一版简单策略筛选。",
            "- yfinance 期权报价可能延迟、缺失或不稳定，提交任何交易前必须在券商界面核对 bid/ask、流动性和合约代码。",
            "- Cash-secured put 默认只使用保守现金，不把保证金购买力当成现金。",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def _is_us_stock_position(position: AccountPosition) -> bool:
    symbol = position.symbol.upper()
    if " " in symbol or "_" in symbol:
        return False
    if "." in symbol and not symbol.endswith(".US"):
        return False
    return position.quantity > 0


def _default_skip_reason(symbol: str) -> str | None:
    normalized = symbol.upper()
    if normalized in PRIMARY_OPTION_UNDERLYINGS:
        return None
    if normalized in OPTION_SCAN_SKIP_REASONS:
        return OPTION_SCAN_SKIP_REASONS[normalized]
    return "不在默认高流动性期权扫描白名单内，本次跳过以避免报告超时。"


def _skipped_position_item(position: AccountPosition, *, as_of: date, reason: str) -> dict[str, Any]:
    return {
        "symbol": position.internal_symbol,
        "name": position.name,
        "quantity": position.quantity,
        "available_quantity": position.available_quantity,
        "cost_price": position.cost_price,
        "underlying_price": _round_optional(position.market_price),
        "as_of": as_of.isoformat(),
        "scan_status": "skipped",
        "skip_reason": reason,
        "suggestions": [],
        "notes": [reason],
    }


def _position_notes(position: AccountPosition, suggestions: list[dict[str, Any]]) -> list[str]:
    notes: list[str] = []
    if position.available_quantity < 100:
        notes.append("持股不足 100 股时 covered call 不成立。")
    if not suggestions:
        notes.append("没有生成符合第一版条件的期权建议。")
    return notes


def _support_price(price: float) -> float:
    return round(price * 0.92, 2)


def _resistance_price(price: float) -> float:
    return round(price * 1.08, 2)


def _days_until(value: date, as_of: date) -> int:
    return (value - as_of).days


def _first_float(*values: Any) -> float | None:
    for value in values:
        number = _optional_float(value)
        if number is not None:
            return number
    return None


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _optional_int(value: Any) -> int | None:
    number = _optional_float(value)
    return None if number is None else int(number)


def _round_optional(value: Any) -> float | None:
    number = _optional_float(value)
    return None if number is None else round(number, 2)


def _print_progress(message: str) -> None:
    print(f"[options-advice] {message}", file=sys.stderr, flush=True)
