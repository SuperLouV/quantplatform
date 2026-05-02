"""Service facade for conservative options strategy evaluation."""

from __future__ import annotations

from quant_platform.options.models import OptionEvaluation, OptionStrategyRequest
from quant_platform.options.prompts import build_options_ai_prompt
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
