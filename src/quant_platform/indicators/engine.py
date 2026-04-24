"""Technical indicator orchestration."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from quant_platform.indicators.base import IndicatorComputation, latest_from_frame, prepare_ohlcv_frame
from quant_platform.indicators.momentum import roc, rsi
from quant_platform.indicators.trend import ema, macd, sma
from quant_platform.indicators.volatility import atr, bollinger_bands
from quant_platform.indicators.volume import volume_ratio


@dataclass(slots=True)
class IndicatorEngine:
    sma_windows: tuple[int, ...] = (5, 10, 20, 50, 200)
    ema_spans: tuple[int, ...] = (12, 26)
    rsi_window: int = 14
    roc_window: int = 10
    bbands_window: int = 20
    bbands_std: float = 2.0
    atr_window: int = 14
    volume_ratio_window: int = 20
    indicator_columns: list[str] = field(default_factory=list)

    def compute(self, frame: pd.DataFrame) -> IndicatorComputation:
        result = prepare_ohlcv_frame(frame)
        close = result["close"]
        high = result["high"]
        low = result["low"]
        volume = result["volume"]

        indicator_columns: list[str] = []

        for window in self.sma_windows:
            column = f"sma_{window}"
            result[column] = sma(close, window)
            indicator_columns.append(column)

        for span in self.ema_spans:
            column = f"ema_{span}"
            result[column] = ema(close, span)
            indicator_columns.append(column)

        macd_result = macd(close)
        result["macd"] = macd_result.macd
        result["macd_signal"] = macd_result.signal
        result["macd_histogram"] = macd_result.histogram
        indicator_columns.extend(["macd", "macd_signal", "macd_histogram"])

        result[f"rsi_{self.rsi_window}"] = rsi(close, self.rsi_window)
        result[f"roc_{self.roc_window}"] = roc(close, self.roc_window)
        indicator_columns.extend([f"rsi_{self.rsi_window}", f"roc_{self.roc_window}"])

        bbands = bollinger_bands(close, self.bbands_window, self.bbands_std)
        result["bbands_upper"] = bbands.upper
        result["bbands_middle"] = bbands.middle
        result["bbands_lower"] = bbands.lower
        indicator_columns.extend(["bbands_upper", "bbands_middle", "bbands_lower"])

        result[f"atr_{self.atr_window}"] = atr(high, low, close, self.atr_window)
        result[f"volume_ratio_{self.volume_ratio_window}"] = volume_ratio(volume, self.volume_ratio_window)
        indicator_columns.extend([f"atr_{self.atr_window}", f"volume_ratio_{self.volume_ratio_window}"])

        self.indicator_columns = indicator_columns
        return IndicatorComputation(
            series=result,
            latest=latest_from_frame(result, indicator_columns),
        )

    def compute_from_parquet(self, path: str | Path) -> IndicatorComputation:
        return self.compute(pd.read_parquet(path))
