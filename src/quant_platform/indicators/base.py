"""Shared helpers for technical indicator computation."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable

import pandas as pd


OHLCV_COLUMNS = ("open", "high", "low", "close", "volume")


@dataclass(slots=True)
class IndicatorComputation:
    series: pd.DataFrame
    latest: dict[str, float | None]


def prepare_ohlcv_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Return a normalized OHLCV frame sorted by timestamp."""

    missing = [column for column in OHLCV_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(f"Missing OHLCV columns: {', '.join(missing)}")

    result = frame.copy()
    if "timestamp" in result.columns:
        result["timestamp"] = pd.to_datetime(result["timestamp"], utc=True)
        result = result.sort_values("timestamp")

    for column in OHLCV_COLUMNS:
        result[column] = pd.to_numeric(result[column], errors="coerce")

    return result.reset_index(drop=True)


def latest_from_frame(frame: pd.DataFrame, columns: Iterable[str]) -> dict[str, float | None]:
    if frame.empty:
        return {column: None for column in columns}

    row = frame.iloc[-1]
    return {column: _to_optional_float(row.get(column)) for column in columns}


def _to_optional_float(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None
    result = float(value)
    if not math.isfinite(result):
        return None
    return result
