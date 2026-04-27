"""Volatility indicators."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(slots=True)
class BollingerBandsResult:
    upper: pd.Series
    middle: pd.Series
    lower: pd.Series


def bollinger_bands(close: pd.Series, window: int = 20, num_std: float = 2.0) -> BollingerBandsResult:
    middle = close.rolling(window=window, min_periods=window).mean()
    std = close.rolling(window=window, min_periods=window).std(ddof=0)
    return BollingerBandsResult(
        upper=middle + num_std * std,
        middle=middle,
        lower=middle - num_std * std,
    )


def atr(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 14) -> pd.Series:
    previous_close = close.shift(1)
    true_range = pd.concat(
        [
            high - low,
            (high - previous_close).abs(),
            (low - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return true_range.ewm(alpha=1 / window, adjust=False, min_periods=window).mean()


def normalized_distance(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    return numerator / denominator.mask(denominator <= 0)
