"""Rule evaluation for tradable universe membership."""

from __future__ import annotations

from quant_platform.screeners.config import ScreeningCriteria
from quant_platform.screeners.models import ScreeningDecision, ScreeningSnapshot, UniverseCandidate


class BasicUniverseScreener:
    def __init__(self, criteria: ScreeningCriteria) -> None:
        self.criteria = criteria

    def evaluate(
        self,
        candidate: UniverseCandidate,
        snapshot: ScreeningSnapshot | None = None,
    ) -> ScreeningDecision:
        reasons: list[str] = []
        if candidate.symbol in self.criteria.excluded_symbols:
            reasons.append("excluded_symbol")

        if snapshot is None:
            return ScreeningDecision(
                symbol=candidate.symbol,
                passed=False,
                status="pending_data",
                reasons=reasons + ["missing_snapshot"],
            )

        if snapshot.exchange and self.criteria.allowed_exchanges:
            if snapshot.exchange not in self.criteria.allowed_exchanges:
                reasons.append("exchange_not_allowed")

        if snapshot.price is None or snapshot.price < self.criteria.min_price:
            reasons.append("price_below_min")

        if snapshot.market_cap is None or snapshot.market_cap < self.criteria.min_market_cap:
            reasons.append("market_cap_below_min")

        if snapshot.avg_dollar_volume is None or snapshot.avg_dollar_volume < self.criteria.min_avg_dollar_volume:
            reasons.append("avg_dollar_volume_below_min")

        if snapshot.listing_months is None or snapshot.listing_months < self.criteria.min_listing_months:
            reasons.append("listing_months_below_min")

        passed = not reasons
        return ScreeningDecision(
            symbol=candidate.symbol,
            passed=passed,
            status="passed" if passed else "rejected",
            reasons=reasons,
        )
