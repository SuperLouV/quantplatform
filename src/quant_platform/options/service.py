"""Service facade for conservative options strategy evaluation and scans."""

from __future__ import annotations

from datetime import date
from typing import Any

from quant_platform.options.models import AccountProfile, OptionEvaluation, OptionStrategyRequest, SellPutScanConfig, SellPutScanResult
from quant_platform.options.prompts import build_options_ai_prompt
from quant_platform.options.scanner import parse_option_volume, scan_sell_put_candidates
from quant_platform.options.strategies import evaluate_cash_secured_put, evaluate_covered_call


class OptionsAssistantService:
    def evaluate(self, request: OptionStrategyRequest) -> OptionEvaluation:
        if request.strategy == "cash_secured_put":
            return evaluate_cash_secured_put(request)
        if request.strategy == "covered_call":
            return evaluate_covered_call(request)
        raise ValueError(f"Unsupported option strategy: {request.strategy}")

    def build_ai_prompt(self, evaluation: OptionEvaluation) -> str:
        return build_options_ai_prompt(evaluation)

    def scan_sell_put(
        self,
        *,
        symbol: str,
        underlying_price: float,
        as_of: date,
        account: AccountProfile,
        expirations: list[date],
        chains_by_expiration: dict[date, list[dict[str, Any]]],
        option_volume_payload: dict[str, Any] | None = None,
        config: SellPutScanConfig | None = None,
    ) -> SellPutScanResult:
        return scan_sell_put_candidates(
            symbol=symbol,
            underlying_price=underlying_price,
            as_of=as_of,
            account=account,
            expirations=expirations,
            chains_by_expiration=chains_by_expiration,
            option_volume=parse_option_volume(option_volume_payload) if option_volume_payload else None,
            config=config,
        )
