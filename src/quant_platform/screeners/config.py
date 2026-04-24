"""Universe and screening configuration models."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from quant_platform.config import load_mapping_file


@dataclass(slots=True)
class SourceConfig:
    enabled: bool
    symbols: list[str]


@dataclass(slots=True)
class ThemeConfig:
    enabled: bool
    symbols: list[str]


@dataclass(slots=True)
class SystemSourceConfig:
    enabled: bool
    seed_symbols: list[str]


@dataclass(slots=True)
class ScreeningCriteria:
    min_price: float
    min_market_cap: float
    min_avg_dollar_volume: float
    min_listing_months: int
    excluded_symbols: set[str]
    allowed_exchanges: set[str]


@dataclass(slots=True)
class UniverseConfig:
    market: str
    manual: SourceConfig
    themes: dict[str, ThemeConfig]
    system: SystemSourceConfig
    ai: SourceConfig
    screening: ScreeningCriteria

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "UniverseConfig":
        universe = data.get("universe", {})
        manual = universe.get("manual", {})
        themes = universe.get("themes", {})
        system = universe.get("system", {})
        ai = universe.get("ai", {})
        screening = universe.get("screening", {})

        return cls(
            market=str(universe.get("market", "us_equities")),
            manual=SourceConfig(
                enabled=bool(manual.get("enabled", True)),
                symbols=_normalize_symbols(manual.get("symbols", [])),
            ),
            themes={
                str(name): ThemeConfig(
                    enabled=bool(config.get("enabled", True)),
                    symbols=_normalize_symbols(config.get("symbols", [])),
                )
                for name, config in themes.items()
                if isinstance(config, dict)
            },
            system=SystemSourceConfig(
                enabled=bool(system.get("enabled", True)),
                seed_symbols=_normalize_symbols(system.get("seed_symbols", [])),
            ),
            ai=SourceConfig(
                enabled=bool(ai.get("enabled", False)),
                symbols=_normalize_symbols(ai.get("symbols", [])),
            ),
            screening=ScreeningCriteria(
                min_price=float(screening.get("min_price", 10)),
                min_market_cap=float(screening.get("min_market_cap", 2_000_000_000)),
                min_avg_dollar_volume=float(screening.get("min_avg_dollar_volume", 10_000_000)),
                min_listing_months=int(screening.get("min_listing_months", 12)),
                excluded_symbols=set(_normalize_symbols(screening.get("excluded_symbols", []))),
                allowed_exchanges=set(_normalize_symbols(screening.get("allowed_exchanges", []))),
            ),
        )


def load_universe_config(path: str | Path) -> UniverseConfig:
    return UniverseConfig.from_mapping(load_mapping_file(path))


def _normalize_symbols(values: Any) -> list[str]:
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, list):
        return []
    return [str(value).upper() for value in values if value]
