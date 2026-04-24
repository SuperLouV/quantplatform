"""Curated stock pools for the first UI version."""

from __future__ import annotations

PRESET_POOLS = [
    {
        "pool_id": "default_core",
        "name": "Default",
        "pool_type": "preset",
        "source": "quantplatform_curated",
        "notes": "Core market names and macro benchmarks for the first view.",
        "symbols": ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "QQQ", "SPY", "TLT", "GLD"],
        "tags": ["core", "default"],
    },
    {
        "pool_id": "tech_leaders",
        "name": "Tech",
        "pool_type": "preset",
        "source": "quantplatform_curated",
        "notes": "Large-cap technology and software leaders.",
        "symbols": ["AAPL", "MSFT", "NVDA", "AMD", "AVGO", "META", "GOOGL", "AMZN", "PLTR", "QCOM", "ASML", "NFLX"],
        "tags": ["technology"],
    },
    {
        "pool_id": "macro_defensive",
        "name": "Macro",
        "pool_type": "preset",
        "source": "quantplatform_curated",
        "notes": "Treasuries, gold, and broad market hedges.",
        "symbols": ["SPY", "QQQ", "TLT", "IEF", "SHY", "TIP", "GLD", "IAU", "SLV"],
        "tags": ["macro", "defensive"],
    },
]
