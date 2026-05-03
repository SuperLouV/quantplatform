"""SELL PUT candidate scanner that can run without option quote access."""

from __future__ import annotations

from datetime import date
from typing import Any

from quant_platform.options.models import (
    AccountProfile,
    OptionVolumeSnapshot,
    SellPutCandidate,
    SellPutScanConfig,
    SellPutScanResult,
)
from quant_platform.time_utils import iso_beijing

CONTRACT_SIZE = 100


def scan_sell_put_candidates(
    *,
    symbol: str,
    underlying_price: float,
    as_of: date,
    account: AccountProfile,
    expirations: list[date],
    chains_by_expiration: dict[date, list[dict[str, Any]]],
    option_volume: OptionVolumeSnapshot | None = None,
    config: SellPutScanConfig | None = None,
) -> SellPutScanResult:
    config = config or SellPutScanConfig()
    normalized_symbol = symbol.upper()
    candidates: list[SellPutCandidate] = []
    rejected_count = 0

    for expiration in sorted(expirations):
        dte = (expiration - as_of).days
        if dte < config.min_dte or dte > config.max_dte:
            continue

        for row in chains_by_expiration.get(expiration, []):
            if not config.include_non_standard and str(row.get("standard")).lower() not in {"true", "1", "yes"}:
                rejected_count += 1
                continue

            strike = _optional_float(row.get("strike"))
            put_symbol = str(row.get("put_symbol") or "")
            if strike is None or not put_symbol:
                rejected_count += 1
                continue

            if strike >= underlying_price:
                rejected_count += 1
                continue

            otm_pct = (underlying_price - strike) / underlying_price * 100
            if otm_pct < config.min_otm_pct * 100 or otm_pct > config.max_otm_pct * 100:
                rejected_count += 1
                continue

            cash_required = strike * CONTRACT_SIZE
            cash_required_pct = cash_required / account.equity * 100 if account.equity > 0 else 0
            reasons: list[str] = [
                f"DTE {dte} 天在扫描区间内。",
                f"Strike 比当前价格低 {otm_pct:.1f}%。",
            ]
            warnings: list[str] = ["缺少具体合约实时 bid/ask，不能计算精确权利金、ROI 和 breakeven。"]
            status = "candidate"

            if cash_required > account.cash:
                status = "blocked"
                warnings.append(f"现金担保需要 ${cash_required:,.2f}，超过当前现金 ${account.cash:,.2f}。")
            elif account.equity > 0 and cash_required > account.equity * config.max_cash_per_trade_pct:
                status = "blocked"
                warnings.append(
                    f"单合约资金占用 {cash_required_pct:.1f}% 超过上限 {config.max_cash_per_trade_pct * 100:.1f}%。"
                )

            if normalized_symbol in config.leveraged_symbols and status != "blocked":
                status = "watch"
                warnings.append("杠杆 ETF 默认只进入观察列表，不标记为低风险候选。")

            candidates.append(
                SellPutCandidate(
                    symbol=normalized_symbol,
                    underlying_price=underlying_price,
                    expiration=expiration,
                    dte=dte,
                    strike=strike,
                    put_symbol=put_symbol,
                    cash_required=cash_required,
                    cash_required_pct=cash_required_pct,
                    otm_pct=otm_pct,
                    status=status,  # type: ignore[arg-type]
                    reasons=reasons,
                    warnings=warnings,
                    option_volume=option_volume,
                )
            )

    candidates = sorted(candidates, key=lambda item: (item.status == "blocked", item.dte, -item.otm_pct, item.cash_required))
    candidates = candidates[: config.max_candidates_per_symbol]
    notes = [
        "V2A 只使用期权链、正股价格和账户现金做基础扫描。",
        "具体合约报价权限缺失时，所有候选都需要人工确认 bid/ask 后才能进一步分析。",
    ]
    return SellPutScanResult(
        symbol=normalized_symbol,
        generated_at_beijing=iso_beijing(),
        candidates=candidates,
        rejected_count=rejected_count,
        notes=notes,
    )


def parse_option_volume(payload: dict[str, Any]) -> OptionVolumeSnapshot:
    return OptionVolumeSnapshot(
        call_volume=_optional_int(payload.get("c")),
        put_volume=_optional_int(payload.get("p")),
    )


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return int(float(value))
