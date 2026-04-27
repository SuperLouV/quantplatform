"""Volume indicators."""

from __future__ import annotations

import pandas as pd


def volume_ratio(volume: pd.Series, window: int = 20) -> pd.Series:
    average_volume = volume.rolling(window=window, min_periods=window).mean()
    return volume / average_volume.mask(average_volume <= 0)


def volume_zscore(volume: pd.Series, window: int = 60) -> pd.Series:
    average_volume = volume.rolling(window=window, min_periods=window).mean()
    std_volume = volume.rolling(window=window, min_periods=window).std(ddof=0)
    return (volume - average_volume) / std_volume.mask(std_volume <= 0)
