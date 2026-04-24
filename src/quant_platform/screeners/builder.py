"""Candidate sourcing and pool construction for the platform universe."""

from __future__ import annotations

from quant_platform.screeners.config import UniverseConfig
from quant_platform.screeners.models import (
    ScreeningDecision,
    ScreeningSnapshot,
    UniverseBuildResult,
    UniverseCandidate,
)
from quant_platform.screeners.rules import BasicUniverseScreener


class UniverseBuilder:
    def __init__(self, config: UniverseConfig) -> None:
        self.config = config
        self.screener = BasicUniverseScreener(config.screening)

    def build(self, snapshots: dict[str, ScreeningSnapshot] | None = None) -> UniverseBuildResult:
        snapshots = snapshots or {}
        candidates: dict[str, UniverseCandidate] = {}

        if self.config.manual.enabled:
            for symbol in self.config.manual.symbols:
                self._add_candidate(candidates, symbol, source="manual")

        for theme_name, theme in self.config.themes.items():
            if not theme.enabled:
                continue
            for symbol in theme.symbols:
                candidate = self._add_candidate(candidates, symbol, source=f"theme:{theme_name}")
                candidate.themes.add(theme_name)
                candidate.tags.add("theme")

        if self.config.system.enabled:
            for symbol in self.config.system.seed_symbols:
                candidate = self._add_candidate(candidates, symbol, source="system_seed")
                candidate.tags.add("system")

        if self.config.ai.enabled:
            for symbol in self.config.ai.symbols:
                candidate = self._add_candidate(candidates, symbol, source="ai")
                candidate.tags.add("ai")

        ordered = sorted(candidates.values(), key=lambda item: item.symbol)
        theme_pool = [candidate for candidate in ordered if candidate.themes]
        system_pool = [
            candidate
            for candidate in ordered
            if "system_seed" in candidate.sources or "ai" in candidate.sources
        ]
        watchlist = ordered

        decisions: list[ScreeningDecision] = [
            self.screener.evaluate(candidate, snapshots.get(candidate.symbol))
            for candidate in ordered
        ]
        passed_symbols = {decision.symbol for decision in decisions if decision.passed}
        tradable_universe = [candidate for candidate in ordered if candidate.symbol in passed_symbols]

        return UniverseBuildResult(
            theme_pool=theme_pool,
            system_pool=system_pool,
            watchlist=watchlist,
            tradable_universe=tradable_universe,
            decisions=decisions,
        )

    def _add_candidate(
        self,
        candidates: dict[str, UniverseCandidate],
        symbol: str,
        *,
        source: str,
    ) -> UniverseCandidate:
        candidate = candidates.setdefault(symbol, UniverseCandidate(symbol=symbol))
        candidate.add_source(source)
        return candidate
