"""Volume indicators."""

from __future__ import annotations

import pandas as pd


def volume_ratio(volume: pd.Series, window: int = 20) -> pd.Series:
    average_volume = volume.rolling(window=window, min_periods=window).mean()
    return volume / average_volume
