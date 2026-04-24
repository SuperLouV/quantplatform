"""Rule-based signal detection from indicator series."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pandas as pd

from quant_platform.core.signal_models import Signal, SignalSummary


@dataclass(slots=True)
class SignalDetector:
    """Detect standardized indicator events without making final trade decisions."""

    def detect(self, symbol: str, indicator_frame: pd.DataFrame) -> SignalSummary:
        if len(indicator_frame.index) < 2:
            return SignalSummary.from_signals(symbol, None, [])

        frame = indicator_frame.sort_values("timestamp") if "timestamp" in indicator_frame.columns else indicator_frame
        previous = frame.iloc[-2]
        current = frame.iloc[-1]
        triggered_at = _row_timestamp(current)
        price = _value(current, "close")
        signals: list[Signal] = []

        self._detect_macd(symbol, previous, current, triggered_at, price, signals)
        self._detect_rsi(symbol, previous, current, triggered_at, price, signals)
        self._detect_bollinger_reclaim(symbol, previous, current, triggered_at, price, signals)
        self._detect_volume_breakout(symbol, previous, current, triggered_at, price, signals)
        self._detect_sma_cross(symbol, previous, current, triggered_at, price, signals)
        self._detect_trend_alignment(symbol, current, triggered_at, price, signals)

        return SignalSummary.from_signals(symbol, triggered_at, signals)

    def _detect_macd(
        self,
        symbol: str,
        previous: pd.Series,
        current: pd.Series,
        triggered_at: datetime,
        price: float | None,
        signals: list[Signal],
    ) -> None:
        prev_macd = _value(previous, "macd")
        prev_signal = _value(previous, "macd_signal")
        curr_macd = _value(current, "macd")
        curr_signal = _value(current, "macd_signal")
        if not _all_numbers(prev_macd, prev_signal, curr_macd, curr_signal):
            return
        values = {"macd": curr_macd, "macd_signal": curr_signal}
        if prev_macd <= prev_signal and curr_macd > curr_signal:
            signals.append(_signal(symbol, "macd_bullish_cross", "long", 3, triggered_at, price, "MACD 上穿 Signal。", values))
        if prev_macd >= prev_signal and curr_macd < curr_signal:
            signals.append(_signal(symbol, "macd_bearish_cross", "short", 3, triggered_at, price, "MACD 下穿 Signal。", values))

    def _detect_rsi(
        self,
        symbol: str,
        previous: pd.Series,
        current: pd.Series,
        triggered_at: datetime,
        price: float | None,
        signals: list[Signal],
    ) -> None:
        prev_rsi = _value(previous, "rsi_14")
        curr_rsi = _value(current, "rsi_14")
        if not _all_numbers(prev_rsi, curr_rsi):
            return
        values = {"rsi_14": curr_rsi}
        if prev_rsi < 30 <= curr_rsi:
            signals.append(_signal(symbol, "rsi_oversold_rebound", "long", 4, triggered_at, price, "RSI 从 30 下方重新上穿 30。", values))
        if prev_rsi > 70 >= curr_rsi:
            signals.append(_signal(symbol, "rsi_overbought_pullback", "short", 4, triggered_at, price, "RSI 从 70 上方重新跌破 70。", values))

    def _detect_bollinger_reclaim(
        self,
        symbol: str,
        previous: pd.Series,
        current: pd.Series,
        triggered_at: datetime,
        price: float | None,
        signals: list[Signal],
    ) -> None:
        prev_close = _value(previous, "close")
        prev_lower = _value(previous, "bbands_lower")
        curr_close = _value(current, "close")
        curr_lower = _value(current, "bbands_lower")
        if not _all_numbers(prev_close, prev_lower, curr_close, curr_lower):
            return
        if prev_close <= prev_lower and curr_close > curr_lower:
            signals.append(
                _signal(
                    symbol,
                    "bbands_lower_reclaim",
                    "long",
                    3,
                    triggered_at,
                    price,
                    "价格触及或跌破布林下轨后重新收回下轨上方。",
                    {"close": curr_close, "bbands_lower": curr_lower},
                )
            )

    def _detect_volume_breakout(
        self,
        symbol: str,
        previous: pd.Series,
        current: pd.Series,
        triggered_at: datetime,
        price: float | None,
        signals: list[Signal],
    ) -> None:
        prev_close = _value(previous, "close")
        prev_sma20 = _value(previous, "sma_20")
        curr_close = _value(current, "close")
        curr_sma20 = _value(current, "sma_20")
        volume_ratio = _value(current, "volume_ratio_20")
        if not _all_numbers(prev_close, prev_sma20, curr_close, curr_sma20, volume_ratio):
            return
        if volume_ratio >= 2 and prev_close <= prev_sma20 and curr_close > curr_sma20:
            signals.append(
                _signal(
                    symbol,
                    "volume_breakout_sma20",
                    "long",
                    5,
                    triggered_at,
                    price,
                    "成交量超过 20 日均量 2 倍并突破 SMA20。",
                    {"close": curr_close, "sma_20": curr_sma20, "volume_ratio_20": volume_ratio},
                )
            )

    def _detect_sma_cross(
        self,
        symbol: str,
        previous: pd.Series,
        current: pd.Series,
        triggered_at: datetime,
        price: float | None,
        signals: list[Signal],
    ) -> None:
        prev_sma20 = _value(previous, "sma_20")
        prev_sma50 = _value(previous, "sma_50")
        curr_sma20 = _value(current, "sma_20")
        curr_sma50 = _value(current, "sma_50")
        if not _all_numbers(prev_sma20, prev_sma50, curr_sma20, curr_sma50):
            return
        values = {"sma_20": curr_sma20, "sma_50": curr_sma50}
        if prev_sma20 <= prev_sma50 and curr_sma20 > curr_sma50:
            signals.append(_signal(symbol, "sma20_cross_above_sma50", "long", 4, triggered_at, price, "SMA20 上穿 SMA50。", values))
        if prev_sma20 >= prev_sma50 and curr_sma20 < curr_sma50:
            signals.append(_signal(symbol, "sma20_cross_below_sma50", "short", 4, triggered_at, price, "SMA20 下穿 SMA50。", values))

    def _detect_trend_alignment(
        self,
        symbol: str,
        current: pd.Series,
        triggered_at: datetime,
        price: float | None,
        signals: list[Signal],
    ) -> None:
        sma20 = _value(current, "sma_20")
        sma50 = _value(current, "sma_50")
        sma200 = _value(current, "sma_200")
        if not _all_numbers(sma20, sma50, sma200):
            return
        values = {"sma_20": sma20, "sma_50": sma50, "sma_200": sma200}
        if sma20 > sma50 > sma200:
            signals.append(_signal(symbol, "bullish_sma_alignment", "long", 3, triggered_at, price, "SMA20 > SMA50 > SMA200，多头排列。", values))
        if sma20 < sma50 < sma200:
            signals.append(_signal(symbol, "bearish_sma_alignment", "short", 3, triggered_at, price, "SMA20 < SMA50 < SMA200，空头排列。", values))


def _signal(
    symbol: str,
    signal_type: str,
    direction: str,
    strength: int,
    triggered_at: datetime,
    price: float | None,
    details: str,
    values: dict[str, float | None],
) -> Signal:
    return Signal(
        symbol=symbol,
        signal_type=signal_type,
        direction=direction,  # type: ignore[arg-type]
        strength=strength,
        triggered_at=triggered_at,
        price=price,
        details=details,
        indicator_values=values,
    )


def _row_timestamp(row: pd.Series) -> datetime:
    if "timestamp" not in row:
        return datetime.now(tz=UTC)
    timestamp = pd.Timestamp(row["timestamp"])
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize(UTC)
    else:
        timestamp = timestamp.tz_convert(UTC)
    return timestamp.to_pydatetime()


def _value(row: pd.Series, key: str) -> float | None:
    value: Any = row.get(key)
    if value is None or pd.isna(value):
        return None
    result = float(value)
    if not math.isfinite(result):
        return None
    return result


def _all_numbers(*values: float | None) -> bool:
    return all(value is not None for value in values)
