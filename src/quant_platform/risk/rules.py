"""Deterministic portfolio risk checks."""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from typing import Any

from quant_platform.portfolio import AccountPosition, AccountSnapshot
from quant_platform.risk.models import (
    ATRStopAdvice,
    EventRisk,
    PDTCheck,
    PositionRisk,
    RiskAssessment,
    RiskPolicy,
    SectorExposure,
)
from quant_platform.time_utils import iso_beijing


class PortfolioRiskAnalyzer:
    """Analyze read-only holdings and produce risk advice."""

    def __init__(self, policy: RiskPolicy | None = None) -> None:
        self.policy = policy or RiskPolicy()

    def assess(
        self,
        account: AccountSnapshot,
        *,
        snapshots_by_symbol: dict[str, dict[str, Any]] | None = None,
        market_events: list[dict[str, Any]] | None = None,
        as_of: date | None = None,
        day_trade_count_5d: int | None = None,
    ) -> RiskAssessment:
        as_of = as_of or date.today()
        snapshots_by_symbol = snapshots_by_symbol or {}
        equity = account.equity_for_risk
        cash = account.cash_for_cash_secured_put
        positions = [
            self._position_risk(position, equity=equity, snapshots_by_symbol=snapshots_by_symbol)
            for position in account.positions
            if position.quantity > 0
        ]
        invested_value = sum(item.market_value or 0 for item in positions)
        sector_exposures = self._sector_exposures(positions, equity=equity)
        pdt = self._pdt_check(equity, day_trade_count_5d)
        event_risks = self._event_risks(
            positions,
            snapshots_by_symbol=snapshots_by_symbol,
            market_events=market_events or [],
            as_of=as_of,
        )
        cash_ratio_pct = (cash / equity * 100) if equity > 0 else None
        hhi = sum(((item.market_value or 0) / equity) ** 2 for item in positions) if equity > 0 else 0
        max_loss_checks = self._max_loss_checks(positions, equity=equity)
        warnings = self._warnings(positions, sector_exposures, pdt, event_risks, cash_ratio_pct, hhi, max_loss_checks)
        recommendations = self._recommendations(positions, sector_exposures, pdt, cash_ratio_pct, hhi, max_loss_checks)
        score = self._score(warnings=warnings, positions=positions, sector_exposures=sector_exposures, cash_ratio_pct=cash_ratio_pct, hhi=hhi)
        return RiskAssessment(
            generated_at_beijing=iso_beijing(),
            currency=account.currency,
            equity=equity,
            cash=cash,
            cash_ratio_pct=cash_ratio_pct,
            invested_value=invested_value,
            position_count=len(positions),
            hhi=hhi,
            health_score=score,
            health_state=_health_state(score),
            pdt=pdt,
            positions=positions,
            sector_exposures=sector_exposures,
            event_risks=event_risks,
            max_loss_checks=max_loss_checks,
            recommendations=recommendations,
            warnings=warnings,
        )

    def _position_risk(
        self,
        position: AccountPosition,
        *,
        equity: float,
        snapshots_by_symbol: dict[str, dict[str, Any]],
    ) -> PositionRisk:
        symbol = position.internal_symbol
        snapshot = snapshots_by_symbol.get(symbol, {})
        market_value = _first_float(position.market_value)
        market_value_price = market_value / position.quantity if market_value is not None and position.quantity > 0 else None
        current_price = _first_float(
            position.market_price,
            market_value_price,
            snapshot.get("current_price"),
            snapshot.get("regular_market_price"),
            snapshot.get("latest_close"),
        )
        if market_value is None and current_price is not None:
            market_value = current_price * position.quantity
        weight_pct = (market_value / equity * 100) if market_value is not None and equity > 0 else None
        unrealized_pl = None
        unrealized_pl_pct = None
        if current_price is not None and position.cost_price not in (None, 0):
            unrealized_pl = (current_price - float(position.cost_price)) * position.quantity
            unrealized_pl_pct = (current_price - float(position.cost_price)) / float(position.cost_price) * 100
        sector = _mapped_sector(symbol, snapshot, position.name)
        atr_stop = self._atr_stop(symbol, position, current_price=current_price, equity=equity, snapshot=snapshot)
        flags: list[str] = []
        if (
            position.market_price is not None
            and market_value_price is not None
            and position.market_price > 0
            and abs(position.market_price - market_value_price) / position.market_price > 0.02
        ):
            flags.append(
                f"账户现价 {position.market_price:.2f} 与市值/股数推算价 {market_value_price:.2f} 差异超过 2%，需核对报价口径。"
            )
        if unrealized_pl_pct is not None and abs(unrealized_pl_pct) >= 50:
            flags.append(
                f"成本盈亏 {unrealized_pl_pct:.1f}% 来自现价 {current_price:.2f} 与成本 {float(position.cost_price):.2f} 的计算；需核对券商成本价是否含转仓/费用。"
            )
        concentration_status = "ok"
        if weight_pct is not None and weight_pct > self.policy.max_position_weight * 100:
            concentration_status = "breach"
            flags.append(f"单股仓位 {weight_pct:.1f}% 超过上限 {self.policy.max_position_weight * 100:.1f}%。")
        max_loss_status = "ok"
        if atr_stop.estimated_loss_pct_of_equity is not None and atr_stop.estimated_loss_pct_of_equity > self.policy.max_single_position_loss_pct * 100:
            max_loss_status = "breach"
            flags.append(
                f"ATR 止损估算亏损 {atr_stop.estimated_loss_pct_of_equity:.1f}% 超过单股风险上限 "
                f"{self.policy.max_single_position_loss_pct * 100:.1f}%。"
            )
        if unrealized_pl_pct is not None and unrealized_pl_pct <= -8:
            flags.append("相对成本回撤超过 8%，需人工复核止损计划。")
        if sector == "Unknown":
            flags.append("缺少行业信息，行业敞口可能被低估。")
        return PositionRisk(
            symbol=symbol,
            name=position.name,
            sector=sector,
            quantity=position.quantity,
            cost_price=position.cost_price,
            current_price=current_price,
            market_value=market_value,
            weight_pct=weight_pct,
            unrealized_pl=unrealized_pl,
            unrealized_pl_pct=unrealized_pl_pct,
            concentration_status=concentration_status,
            max_loss_status=max_loss_status,
            atr_stop=atr_stop,
            flags=flags,
        )

    def _atr_stop(
        self,
        symbol: str,
        position: AccountPosition,
        *,
        current_price: float | None,
        equity: float,
        snapshot: dict[str, Any],
    ) -> ATRStopAdvice:
        indicators = snapshot.get("indicators") if isinstance(snapshot.get("indicators"), dict) else {}
        atr = _first_float(indicators.get("atr_14") if isinstance(indicators, dict) else None)
        notes: list[str] = []
        if current_price is None:
            return ATRStopAdvice(symbol, None, atr, None, None, None, None, "missing_price", ["缺少当前价格，无法计算 ATR 止损。"])
        if atr is None or atr <= 0:
            return ATRStopAdvice(symbol, current_price, None, None, None, None, None, "missing_atr", ["缺少 atr_14，先补齐本地日线指标。"])
        stop_price = max(0.01, current_price - atr * self.policy.atr_stop_multiplier)
        stop_distance_pct = (current_price - stop_price) / current_price * 100
        estimated_loss = max(0, (current_price - stop_price) * position.quantity)
        estimated_loss_pct = estimated_loss / equity * 100 if equity > 0 else None
        if stop_distance_pct > 15:
            notes.append("ATR 止损距离较宽，可能说明波动率过高或入场点偏远。")
        return ATRStopAdvice(
            symbol=symbol,
            reference_price=current_price,
            atr_14=atr,
            stop_price=stop_price,
            stop_distance_pct=stop_distance_pct,
            estimated_loss=estimated_loss,
            estimated_loss_pct_of_equity=estimated_loss_pct,
            status="ok",
            notes=notes,
        )

    def _sector_exposures(self, positions: list[PositionRisk], *, equity: float) -> list[SectorExposure]:
        grouped: dict[str, list[PositionRisk]] = {}
        for position in positions:
            grouped.setdefault(position.sector, []).append(position)
        result: list[SectorExposure] = []
        for sector, items in grouped.items():
            market_value = sum(item.market_value or 0 for item in items)
            weight_pct = market_value / equity * 100 if equity > 0 else 0
            status = "breach" if weight_pct > self.policy.max_sector_weight * 100 else "ok"
            result.append(
                SectorExposure(
                    sector=sector,
                    market_value=market_value,
                    weight_pct=weight_pct,
                    position_count=len(items),
                    status=status,
                    symbols=[item.symbol for item in items],
                )
            )
        return sorted(result, key=lambda item: (-item.weight_pct, item.sector))

    def _pdt_check(self, equity: float, day_trade_count_5d: int | None) -> PDTCheck:
        below = equity < self.policy.pdt_equity_threshold
        if day_trade_count_5d is None:
            status = "watch" if below else "ok"
            message = (
                f"账户权益低于 ${self.policy.pdt_equity_threshold:,.0f}，且缺少 5 日 day trade 次数；避免日内频繁开平。"
                if below
                else "账户权益高于 PDT 门槛；仍需在券商侧确认 day trade 统计。"
            )
            return PDTCheck(equity, self.policy.pdt_equity_threshold, None, status, message)
        if below and day_trade_count_5d >= self.policy.pdt_day_trade_limit_5d:
            return PDTCheck(
                equity,
                self.policy.pdt_equity_threshold,
                day_trade_count_5d,
                "breach",
                "账户低于 PDT 门槛且 5 个交易日内 day trade 次数接近/达到限制。",
            )
        return PDTCheck(equity, self.policy.pdt_equity_threshold, day_trade_count_5d, "ok" if not below else "watch", "PDT 检查未发现硬性超限。")

    def _event_risks(
        self,
        positions: list[PositionRisk],
        *,
        snapshots_by_symbol: dict[str, dict[str, Any]],
        market_events: list[dict[str, Any]],
        as_of: date,
    ) -> list[EventRisk]:
        end = as_of + timedelta(days=self.policy.event_risk_window_days)
        risks: list[EventRisk] = []
        held_symbols = {item.symbol for item in positions}
        for symbol in held_symbols:
            snapshot = snapshots_by_symbol.get(symbol, {})
            earnings = _parse_date(snapshot.get("next_earnings_date"))
            if earnings and as_of <= earnings <= end:
                risks.append(EventRisk("earnings", symbol, f"{symbol} 财报窗口", earnings, "high", "snapshot", "watch"))
        for event in market_events:
            event_date = _parse_date(event.get("event_time"))
            if event_date is None or event_date < as_of or event_date > end:
                continue
            importance = str(event.get("importance") or "medium")
            if importance not in {"high", "medium"}:
                continue
            risks.append(
                EventRisk(
                    "macro",
                    None,
                    str(event.get("title") or "market event"),
                    event_date,
                    importance,
                    str(event.get("source") or "market_events"),
                    "watch",
                )
            )
        return sorted(risks, key=lambda item: (item.event_date or date.max, item.symbol or ""))

    def _max_loss_checks(self, positions: list[PositionRisk], *, equity: float) -> dict[str, Any]:
        total_atr_loss = sum(item.atr_stop.estimated_loss or 0 for item in positions)
        total_unrealized_loss = abs(sum(min(item.unrealized_pl or 0, 0) for item in positions))
        return {
            "total_atr_stop_loss": round(total_atr_loss, 2),
            "total_atr_stop_loss_pct_of_equity": round(total_atr_loss / equity * 100, 2) if equity > 0 else None,
            "total_unrealized_loss": round(total_unrealized_loss, 2),
            "total_unrealized_loss_pct_of_equity": round(total_unrealized_loss / equity * 100, 2) if equity > 0 else None,
            "atr_status": "breach" if equity > 0 and total_atr_loss / equity > self.policy.max_total_atr_risk_pct else "ok",
            "drawdown_status": "breach" if equity > 0 and total_unrealized_loss / equity > self.policy.max_portfolio_drawdown else "ok",
        }

    def _warnings(
        self,
        positions: list[PositionRisk],
        sectors: list[SectorExposure],
        pdt: PDTCheck,
        events: list[EventRisk],
        cash_ratio_pct: float | None,
        hhi: float,
        max_loss_checks: dict[str, Any],
    ) -> list[str]:
        warnings: list[str] = []
        warnings.extend(flag for item in positions for flag in item.flags)
        warnings.extend(f"{sector.sector} 行业敞口 {sector.weight_pct:.1f}% 超过上限。" for sector in sectors if sector.status == "breach")
        if pdt.status in {"watch", "breach"}:
            warnings.append(pdt.message)
        if cash_ratio_pct is not None and cash_ratio_pct < self.policy.min_cash_ratio * 100:
            warnings.append(f"现金比例 {cash_ratio_pct:.1f}% 低于下限 {self.policy.min_cash_ratio * 100:.1f}%。")
        if hhi > self.policy.high_hhi_threshold:
            warnings.append(f"持仓 HHI {hhi:.3f} 偏高，组合集中度较高。")
        if max_loss_checks.get("atr_status") == "breach":
            warnings.append("组合 ATR 止损估算亏损超过总风险预算。")
        if max_loss_checks.get("drawdown_status") == "breach":
            warnings.append("当前未实现亏损超过组合最大亏损限额。")
        if events:
            warnings.append(f"未来 {self.policy.event_risk_window_days} 天存在 {len(events)} 条持仓/宏观事件风险。")
        return _ordered_unique(warnings)

    def _recommendations(
        self,
        positions: list[PositionRisk],
        sectors: list[SectorExposure],
        pdt: PDTCheck,
        cash_ratio_pct: float | None,
        hhi: float,
        max_loss_checks: dict[str, Any],
    ) -> list[str]:
        recommendations: list[str] = []
        overweight = sorted(
            (item for item in positions if item.concentration_status == "breach"),
            key=lambda item: (-(item.weight_pct or 0), item.symbol),
        )
        for item in overweight[:5]:
            implied_equity = item.market_value / (item.weight_pct / 100) if item.market_value is not None and item.weight_pct else None
            target_value = implied_equity * self.policy.max_position_weight if implied_equity is not None else None
            reduce_value = max(0.0, item.market_value - target_value) if item.market_value is not None and target_value is not None else None
            reduce_shares = reduce_value / item.current_price if reduce_value is not None and item.current_price not in (None, 0) else None
            detail = f"约减 ${reduce_value:,.0f}" if reduce_value is not None else "按当前权益重新估算减仓金额"
            if reduce_shares is not None:
                detail += f" / {reduce_shares:.1f} 股"
            recommendations.append(
                f"{item.symbol} 单股权重 {item.weight_pct:.1f}% 高于 {self.policy.max_position_weight * 100:.1f}% 上限，"
                f"建议分批降到上限附近（{detail}），降到位前不再加仓。"
            )
        if any(sector.status == "breach" for sector in sectors):
            for sector in sectors:
                if sector.status != "breach":
                    continue
                recommendations.append(
                    f"{sector.sector} 敞口 {sector.weight_pct:.1f}% 高于 {self.policy.max_sector_weight * 100:.1f}% 上限，"
                    f"新增候选先避开该行业；若要降回上限以内，优先从该行业内单股超限或 ATR 风险最高的标的处理。"
                )
        if any(item.atr_stop.status == "ok" for item in positions):
            recommendations.append("使用 ATR 止损价作为人工复盘参考，不作为自动卖出指令。")
        if pdt.status in {"watch", "breach"}:
            recommendations.append("账户低于 PDT 门槛时，避免 5 个交易日内多次日内开平同一标的。")
        if cash_ratio_pct is not None and cash_ratio_pct < self.policy.min_cash_ratio * 100:
            recommendations.append("现金比例偏低时，cash-secured put 应使用更严格的资金占用上限。")
        if hhi > self.policy.high_hhi_threshold:
            recommendations.append("组合 HHI 偏高，可用减小新仓、分散行业或等待回撤来降低集中风险。")
        if max_loss_checks.get("atr_status") == "breach":
            recommendations.append("组合 ATR 风险超预算时，新增候选只进入观察，不进入交易计划。")
        return _ordered_unique(recommendations) or ["未发现硬性风控超限，仍需人工确认价格、事件和券商账户状态。"]

    def _score(
        self,
        *,
        warnings: list[str],
        positions: list[PositionRisk],
        sector_exposures: list[SectorExposure],
        cash_ratio_pct: float | None,
        hhi: float,
    ) -> int:
        score = 100 - min(len(warnings) * 6, 42)
        score -= sum(8 for item in positions if item.concentration_status == "breach")
        score -= sum(10 for item in sector_exposures if item.status == "breach")
        if cash_ratio_pct is not None and cash_ratio_pct < self.policy.min_cash_ratio * 100:
            score -= 8
        if hhi > self.policy.high_hhi_threshold:
            score -= 8
        return max(0, min(100, round(score)))


def _health_state(score: int) -> str:
    if score >= 80:
        return "健康"
    if score >= 60:
        return "观察"
    return "风险复核"


def _first_float(*values: Any) -> float | None:
    for value in values:
        if value in (None, ""):
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            return number
    return None


_SECTOR_FALLBACKS = {
    "VOO": "美国大盘 ETF",
    "SPY": "美国大盘 ETF",
    "QQQ": "美国大型科技/成长 ETF",
    "EWT": "台湾市场 ETF（半导体权重高）",
    "EWJ": "日本市场 ETF",
    "DRAM": "半导体 ETF",
    "BRK.B": "金融/保险控股",
    "CRCL": "金融科技",
    "XE": "能源/核能设备",
    "NOK": "通信设备",
}


def _mapped_sector(symbol: str, snapshot: dict[str, Any], name: str | None) -> str:
    direct = _first_string(snapshot.get("sector_zh"), snapshot.get("sector"))
    if direct and direct.lower() != "unknown":
        return direct
    fallback = _SECTOR_FALLBACKS.get(symbol.upper())
    if fallback:
        return fallback
    quote_type = str(snapshot.get("quote_type") or snapshot.get("type") or "").lower()
    name_text = str(name or snapshot.get("company_name") or "").lower()
    if "etf" in quote_type or " etf" in name_text or "fund" in name_text:
        return "ETF/基金"
    return "Unknown"


def _first_string(*values: Any) -> str | None:
    for value in values:
        if value in (None, ""):
            continue
        return str(value)
    return None


def _parse_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(str(value).split(" ", 1)[0])
        except ValueError:
            return None


def _ordered_unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))
