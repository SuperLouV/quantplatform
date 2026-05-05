"""Risk policy loading helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from quant_platform.config import load_mapping_file
from quant_platform.risk.models import RiskPolicy


def load_risk_policy(path: str | Path | None = None) -> RiskPolicy:
    if path is None:
        return RiskPolicy()
    config_path = Path(path)
    if not config_path.exists():
        return RiskPolicy()
    payload = load_mapping_file(config_path)
    risk = payload.get("risk") if isinstance(payload.get("risk"), dict) else payload
    if not isinstance(risk, dict):
        return RiskPolicy()
    return RiskPolicy(
        max_position_weight=_float(risk, "max_position_weight", RiskPolicy.max_position_weight),
        max_sector_weight=_float(risk, "max_sector_weight", RiskPolicy.max_sector_weight),
        max_open_positions=int(_float(risk, "max_open_positions", RiskPolicy.max_open_positions)),
        max_portfolio_drawdown=_float(risk, "max_portfolio_drawdown", RiskPolicy.max_portfolio_drawdown),
        max_single_position_loss_pct=_float(risk, "max_single_position_loss_pct", RiskPolicy.max_single_position_loss_pct),
        max_total_atr_risk_pct=_float(risk, "max_total_atr_risk_pct", RiskPolicy.max_total_atr_risk_pct),
        atr_stop_multiplier=_float(risk, "atr_stop_multiplier", RiskPolicy.atr_stop_multiplier),
        pdt_equity_threshold=_float(risk, "pdt_equity_threshold", RiskPolicy.pdt_equity_threshold),
        pdt_day_trade_limit_5d=int(_float(risk, "pdt_day_trade_limit_5d", RiskPolicy.pdt_day_trade_limit_5d)),
        event_risk_window_days=int(_float(risk, "event_risk_window_days", RiskPolicy.event_risk_window_days)),
        min_cash_ratio=_float(risk, "min_cash_ratio", RiskPolicy.min_cash_ratio),
        high_hhi_threshold=_float(risk, "high_hhi_threshold", RiskPolicy.high_hhi_threshold),
    )


def _float(payload: dict[str, Any], key: str, default: float | int) -> float:
    value = payload.get(key, default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)
