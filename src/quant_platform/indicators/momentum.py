"""Momentum indicators."""

from __future__ import annotations

import pandas as pd


def rsi(close: pd.Series, window: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1 / window, adjust=False, min_periods=window).mean()
    avg_loss = loss.ewm(alpha=1 / window, adjust=False, min_periods=window).mean()
    rs = avg_gain / avg_loss
    result = 100 - (100 / (1 + rs))
    result = result.mask((avg_loss == 0) & (avg_gain > 0), 100)
    result = result.mask((avg_loss == 0) & (avg_gain == 0), 50)
    return result


def roc(close: pd.Series, window: int = 10) -> pd.Series:
    return close.pct_change(periods=window) * 100
