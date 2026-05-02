"""Rule-based checks for simple conservative options strategies."""

from __future__ import annotations

from quant_platform.options.models import OptionDecision, OptionEvaluation, OptionStrategyRequest

CONTRACT_SIZE = 100


def evaluate_cash_secured_put(request: OptionStrategyRequest) -> OptionEvaluation:
    account = request.account
    stock = request.stock
    contract = request.contract
    dte = contract.dte(stock.as_of)
    premium = contract.mid
    premium_income = premium * CONTRACT_SIZE
    capital_required = contract.strike * CONTRACT_SIZE
    max_loss = max(0, capital_required - premium_income)
    breakeven = contract.strike - premium
    spread_pct = contract.spread_pct()

    violations: list[str] = []
    warnings: list[str] = []
    confirmations: list[str] = []

    if request.strategy != "cash_secured_put":
        violations.append("策略类型不是 cash_secured_put。")
    if contract.option_type != "put":
        violations.append("Cash-secured put 必须使用 put 合约。")
    if not account.allow_assignment:
        violations.append("账户策略不允许被指派买入股票。")
    if capital_required > account.cash:
        violations.append(f"现金担保需要 ${capital_required:,.2f}，超过当前现金 ${account.cash:,.2f}。")
    if capital_required > account.equity * account.max_cash_per_trade_pct:
        violations.append(
            f"单笔资金占用 {capital_required / account.equity * 100:.1f}% 超过上限 "
            f"{account.max_cash_per_trade_pct * 100:.1f}%。"
        )
    if max_loss > account.equity * account.max_loss_pct:
        violations.append(
            f"极端最大亏损估算 {max_loss / account.equity * 100:.1f}% 超过上限 "
            f"{account.max_loss_pct * 100:.1f}%。"
        )
    if dte < 14 or dte > 60:
        warnings.append("DTE 不在第一版保守区间 14-60 天内。")
    if contract.delta is not None and not (-0.35 <= contract.delta <= -0.10):
        warnings.append("Put delta 不在第一版保守区间 -0.35 到 -0.10。")
    if spread_pct is None or spread_pct > 0.15:
        warnings.append("Bid/ask spread 偏宽或无法计算，成交成本风险较高。")
    if contract.open_interest is not None and contract.open_interest < 100:
        warnings.append("Open interest 低于 100，流动性可能不足。")
    if stock.earnings_days is not None and 0 <= stock.earnings_days <= 7:
        warnings.append("财报日前 7 天内不适合盲目卖 put。")
    if stock.support_price is not None and breakeven > stock.support_price:
        warnings.append("Breakeven 高于输入支撑位，安全边际不足。")
    if stock.market_risk_state and "Risk Off" in stock.market_risk_state:
        warnings.append("市场处于 Risk Off，不适合新增卖方风险敞口。")

    if not violations:
        confirmations.append("资金担保、合约方向和基本账户约束通过。")
    if stock.support_price is not None and breakeven <= stock.support_price:
        confirmations.append("Breakeven 不高于输入支撑位，价格缓冲相对合理。")

    return _evaluation(
        request=request,
        capital_required=capital_required,
        premium_income=premium_income,
        max_loss=max_loss,
        breakeven=breakeven,
        dte=dte,
        spread_pct=spread_pct,
        violations=violations,
        warnings=warnings,
        confirmations=confirmations,
    )


def evaluate_covered_call(request: OptionStrategyRequest) -> OptionEvaluation:
    account = request.account
    stock = request.stock
    contract = request.contract
    dte = contract.dte(stock.as_of)
    premium = contract.mid
    premium_income = premium * CONTRACT_SIZE
    stock_value = stock.current_price * CONTRACT_SIZE
    max_loss = max(0, stock_value - premium_income)
    spread_pct = contract.spread_pct()

    violations: list[str] = []
    warnings: list[str] = []
    confirmations: list[str] = []

    if request.strategy != "covered_call":
        violations.append("策略类型不是 covered_call。")
    if contract.option_type != "call":
        violations.append("Covered call 必须使用 call 合约。")
    if account.stock_shares < CONTRACT_SIZE:
        violations.append("Covered call 需要至少持有 100 股正股。")
    if account.stock_cost_basis is not None and contract.strike < account.stock_cost_basis:
        warnings.append("Call strike 低于持仓成本价，被行权可能锁定亏损。")
    if contract.strike <= stock.current_price:
        warnings.append("Call strike 不高于当前股价，被行权概率和机会成本较高。")
    if dte < 7 or dte > 60:
        warnings.append("DTE 不在第一版保守区间 7-60 天内。")
    if contract.delta is not None and not (0.10 <= contract.delta <= 0.35):
        warnings.append("Call delta 不在第一版保守区间 0.10 到 0.35。")
    if spread_pct is None or spread_pct > 0.15:
        warnings.append("Bid/ask spread 偏宽或无法计算，成交成本风险较高。")
    if stock.earnings_days is not None and 0 <= stock.earnings_days <= 7:
        warnings.append("财报日前 7 天内卖 covered call 可能错过跳空上涨。")

    if not violations:
        confirmations.append("持股数量、合约方向和基本账户约束通过。")
    if account.stock_cost_basis is not None and contract.strike >= account.stock_cost_basis:
        confirmations.append("Strike 不低于持仓成本价。")

    return _evaluation(
        request=request,
        capital_required=0,
        premium_income=premium_income,
        max_loss=max_loss,
        breakeven=None if account.stock_cost_basis is None else account.stock_cost_basis - premium,
        dte=dte,
        spread_pct=spread_pct,
        violations=violations,
        warnings=warnings,
        confirmations=confirmations,
    )


def _evaluation(
    *,
    request: OptionStrategyRequest,
    capital_required: float,
    premium_income: float,
    max_loss: float,
    breakeven: float | None,
    dte: int,
    spread_pct: float | None,
    violations: list[str],
    warnings: list[str],
    confirmations: list[str],
) -> OptionEvaluation:
    return_on_capital = premium_income / capital_required * 100 if capital_required > 0 else None
    annualized = return_on_capital * 365 / dte if return_on_capital is not None and dte > 0 else None
    return OptionEvaluation(
        strategy=request.strategy,
        symbol=request.stock.symbol,
        decision=_decision(violations, warnings),
        capital_required=capital_required,
        premium_income=premium_income,
        max_loss_estimate=max_loss,
        breakeven=breakeven,
        return_on_capital_pct=return_on_capital,
        annualized_return_pct=annualized,
        dte=dte,
        spread_pct=spread_pct * 100 if spread_pct is not None else None,
        violations=violations,
        warnings=warnings,
        confirmations=confirmations,
        ai_context={
            "request": request.to_dict(),
            "risk_note": "这是规则层风险检查，不是自动下单指令。AI 只能基于这些事实做解释和提问。",
        },
    )


def _decision(violations: list[str], warnings: list[str]) -> OptionDecision:
    if violations:
        return "不适合"
    if warnings:
        return "继续观察"
    return "符合策略"
