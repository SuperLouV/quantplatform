"""Trend indicators."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


def sma(close: pd.Series, window: int) -> pd.Series:
    return close.rolling(window=window, min_periods=window).mean()


def ema(close: pd.Series, span: int) -> pd.Series:
    return close.ewm(span=span, adjust=False, min_periods=span).mean()


@dataclass(slots=True)
class MACDResult:
    macd: pd.Series
    signal: pd.Series
    histogram: pd.Series


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> MACDResult:
    fast_line = ema(close, fast)
    slow_line = ema(close, slow)
    macd_line = fast_line - slow_line
    signal_line = macd_line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    return MACDResult(
        macd=macd_line,
        signal=signal_line,
        histogram=macd_line - signal_line,
    )
