"""Yahoo Finance research client placeholder."""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, date, datetime
from importlib.util import find_spec
from typing import Any

import pandas as pd
import yfinance as yf

from quant_platform.clients.base import BaseDataClient
from quant_platform.clients.protection import ProviderRequestGuard, ProviderRequestPolicy
from quant_platform.config import DataConfig
from quant_platform.core.models import Bar, DataRequest, Security, TradingCalendarEvent
from quant_platform.time_utils import iso_beijing, to_us_eastern


class YFinanceClient(BaseDataClient):
    provider_name = "yfinance"

    def __init__(
        self,
        policy: ProviderRequestPolicy | None = None,
        *,
        history_repair: bool = True,
        history_prepost: bool = False,
    ) -> None:
        self.policy = policy or ProviderRequestPolicy()
        self.history_repair = history_repair and find_spec("scipy") is not None
        self.history_prepost = history_prepost
        self.guard = ProviderRequestGuard(self.policy)

    @classmethod
    def from_data_config(cls, config: DataConfig) -> "YFinanceClient":
        return cls(
            ProviderRequestPolicy(
                min_interval_seconds=config.request_min_interval_seconds,
                max_retries=config.request_max_retries,
                backoff_seconds=config.request_backoff_seconds,
                timeout_seconds=config.request_timeout_seconds,
            ),
            history_repair=config.yfinance_history_repair,
            history_prepost=config.yfinance_history_prepost,
        )

    def fetch_bars(self, request: DataRequest) -> list[Bar]:
        return self.guard.call(
            f"fetch_bars({request.symbol})",
            lambda: self._fetch_bars(request),
        )

    def _fetch_bars(self, request: DataRequest) -> list[Bar]:
        ticker = yf.Ticker(request.symbol)
        history = _ticker_history(
            ticker,
            timeout=self.policy.timeout_seconds,
            start=_coerce_history_date(request.start),
            end=_coerce_history_date(request.end),
            interval=request.interval,
            auto_adjust=request.adjusted,
            actions=False,
            repair=self.history_repair,
            prepost=self.history_prepost,
        )
        if history.empty:
            return []

        history = history.reset_index()
        timestamp_column = "Date" if "Date" in history.columns else history.columns[0]

        bars: list[Bar] = []
        for row in history.to_dict(orient="records"):
            bars.append(
                Bar(
                    symbol=request.symbol,
                    timestamp=_normalize_timestamp(row[timestamp_column]),
                    open=_to_float(row.get("Open")),
                    high=_to_float(row.get("High")),
                    low=_to_float(row.get("Low")),
                    close=_to_float(row.get("Close")),
                    volume=_to_float(row.get("Volume")),
                    provider=self.provider_name,
                    adjusted=request.adjusted,
                )
            )
        return bars

    def fetch_security(self, symbol: str) -> Security | None:
        return self.guard.call(
            f"fetch_security({symbol})",
            lambda: self._fetch_security(symbol),
        )

    def _fetch_security(self, symbol: str) -> Security | None:
        ticker = yf.Ticker(symbol)
        info = ticker.info or {}
        if not info:
            return None
        return Security(
            symbol=symbol,
            name=info.get("shortName") or info.get("longName"),
            exchange=info.get("exchange"),
            sector=info.get("sector"),
            industry=info.get("industry"),
            market_cap=_optional_float(info.get("marketCap")),
            currency=info.get("currency"),
            extra=info,
        )

    def fetch_events(self, symbol: str) -> list[TradingCalendarEvent]:
        return self.guard.call(
            f"fetch_events({symbol})",
            lambda: self._fetch_events(symbol),
        )

    def _fetch_events(self, symbol: str) -> list[TradingCalendarEvent]:
        ticker = yf.Ticker(symbol)
        events: list[TradingCalendarEvent] = []

        calendar = ticker.calendar
        if isinstance(calendar, pd.DataFrame) and not calendar.empty:
            data = calendar.to_dict()
            for label, values in data.items():
                normalized_label = str(label).strip().lower().replace(" ", "_")
                event_date = _extract_first_date(values.values())
                if event_date is None:
                    continue
                events.append(
                    TradingCalendarEvent(
                        symbol=symbol,
                        event_type=normalized_label,
                        event_date=event_date,
                        provider=self.provider_name,
                        detail=str(asdict(Security(symbol=symbol, extra={"source": "yfinance_calendar"}))),
                    )
                )
        return events

    def fetch_raw_history(self, request: DataRequest) -> list[dict[str, Any]]:
        bars = self.fetch_bars(request)
        return [
            {
                "symbol": bar.symbol,
                "timestamp": bar.timestamp.isoformat(),
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": bar.volume,
                "provider": bar.provider,
                "adjusted": bar.adjusted,
            }
            for bar in bars
        ]

    def fetch_quote_snapshot(self, symbol: str) -> dict[str, Any]:
        return self.guard.call(
            f"fetch_quote_snapshot({symbol})",
            lambda: self._fetch_quote_snapshot(symbol),
        )

    def _fetch_quote_snapshot(self, symbol: str) -> dict[str, Any]:
        ticker = yf.Ticker(symbol)
        fast_info = _safe_dict(lambda: ticker.fast_info)
        history = _ticker_history(
            ticker,
            timeout=self.policy.timeout_seconds,
            period="5d",
            interval="1d",
            auto_adjust=False,
            actions=False,
            repair=self.history_repair,
            prepost=self.history_prepost,
        )
        info = _safe_dict(lambda: ticker.info)

        latest_row = history.iloc[-1] if not history.empty else None
        previous_row = history.iloc[-2] if len(history.index) > 1 else None
        latest_history_date_us = _history_market_date_us(history.index[-1]) if latest_row is not None else None

        previous_close = (
            _optional_float(previous_row["Close"])
            if previous_row is not None
            else _optional_float(fast_info.get("previousClose")) or _optional_float(info.get("previousClose"))
        )
        latest_close = (
            _optional_float(latest_row["Close"])
            if latest_row is not None
            else _optional_float(fast_info.get("lastPrice")) or _optional_float(info.get("currentPrice"))
        )
        current_price = (
            _optional_float(info.get("currentPrice"))
            or _optional_float(info.get("regularMarketPrice"))
            or _optional_float(fast_info.get("lastPrice"))
            or latest_close
        )
        regular_market_price = (
            _optional_float(info.get("regularMarketPrice"))
            or _optional_float(fast_info.get("lastPrice"))
            or latest_close
        )
        change_percent = None
        change_base = current_price if current_price is not None else latest_close
        if change_base is not None and previous_close not in (None, 0):
            change_percent = ((change_base - previous_close) / previous_close) * 100

        earnings_date = _extract_calendar_date(_safe_value(lambda: ticker.calendar))

        return {
            "symbol": symbol,
            "company_name": info.get("shortName") or info.get("longName"),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "exchange": fast_info.get("exchange") or info.get("exchange"),
            "currency": fast_info.get("currency") or info.get("currency"),
            "open_price": _optional_float(latest_row["Open"]) if latest_row is not None else _optional_float(fast_info.get("open")),
            "high_price": _optional_float(latest_row["High"]) if latest_row is not None else _optional_float(fast_info.get("dayHigh")),
            "low_price": _optional_float(latest_row["Low"]) if latest_row is not None else _optional_float(fast_info.get("dayLow")),
            "latest_close": latest_close,
            "current_price": current_price,
            "regular_market_price": regular_market_price,
            "pre_market_price": _optional_float(info.get("preMarketPrice")),
            "post_market_price": _optional_float(info.get("postMarketPrice")),
            "market_state": info.get("marketState"),
            "latest_history_date_us": latest_history_date_us,
            "snapshot_refreshed_at_beijing": iso_beijing(),
            "market_timezone": "America/New_York",
            "previous_close": previous_close,
            "change_percent": change_percent,
            "latest_volume": _optional_float(latest_row["Volume"]) if latest_row is not None else _optional_float(fast_info.get("lastVolume")),
            "market_cap": _optional_float(fast_info.get("marketCap")) or _optional_float(info.get("marketCap")),
            "avg_dollar_volume": _optional_float(fast_info.get("tenDayAverageVolume")) * latest_close
            if _optional_float(fast_info.get("tenDayAverageVolume")) is not None and latest_close is not None
            else None,
            "trailing_pe": _optional_float(info.get("trailingPE")),
            "forward_pe": _optional_float(info.get("forwardPE")),
            "next_earnings_date": earnings_date,
        }

    def fetch_chart_history(self, symbol: str, period: str = "6mo", interval: str = "1d") -> list[dict[str, Any]]:
        return self.guard.call(
            f"fetch_chart_history({symbol})",
            lambda: self._fetch_chart_history(symbol, period=period, interval=interval),
        )

    def _fetch_chart_history(self, symbol: str, period: str = "6mo", interval: str = "1d") -> list[dict[str, Any]]:
        ticker = yf.Ticker(symbol)
        history = _ticker_history(
            ticker,
            timeout=self.policy.timeout_seconds,
            period=period,
            interval=interval,
            auto_adjust=False,
            actions=False,
            repair=self.history_repair,
            prepost=self.history_prepost,
        )
        if history.empty:
            return []

        history = history.reset_index()
        timestamp_column = "Date" if "Date" in history.columns else history.columns[0]
        points: list[dict[str, Any]] = []
        for row in history.to_dict(orient="records"):
            points.append(
                {
                    "timestamp": _normalize_timestamp(row[timestamp_column]).isoformat(),
                    "open": _optional_float(row.get("Open")),
                    "high": _optional_float(row.get("High")),
                    "low": _optional_float(row.get("Low")),
                    "close": _optional_float(row.get("Close")),
                    "volume": _optional_float(row.get("Volume")),
                }
            )
        return points

    def search_symbols(self, query: str, limit: int = 8) -> list[dict[str, Any]]:
        if not query.strip():
            return []

        return self.guard.call(
            f"search_symbols({query})",
            lambda: self._search_symbols(query, limit),
        )

    def _search_symbols(self, query: str, limit: int = 8) -> list[dict[str, Any]]:
        search = _search(query, limit)
        results: list[dict[str, Any]] = []
        for item in (search.quotes or [])[:limit]:
            symbol = item.get("symbol")
            if not symbol:
                continue
            results.append(
                {
                    "symbol": symbol.upper(),
                    "name": item.get("shortname") or item.get("longname") or item.get("name"),
                    "exchange": item.get("exchange") or item.get("exchDisp"),
                    "type": item.get("quoteType") or item.get("typeDisp"),
                }
            )
        return results


def _ticker_history(ticker: Any, *, timeout: float, **kwargs: Any) -> pd.DataFrame:
    try:
        return ticker.history(timeout=timeout, **kwargs)
    except TypeError:
        return ticker.history(**kwargs)


def _search(query: str, limit: int) -> Any:
    try:
        return yf.Search(query, max_results=limit)
    except TypeError:
        return yf.Search(query)


def _safe_dict(loader: Any) -> dict[str, Any]:
    try:
        value = loader()
        return dict(value or {})
    except Exception:  # noqa: BLE001 - yfinance metadata helpers can fail while price history still works.
        return {}


def _safe_value(loader: Any) -> Any | None:
    try:
        return loader()
    except Exception:  # noqa: BLE001 - yfinance optional metadata can fail independently of prices.
        return None


def _coerce_history_date(value: date | datetime | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    return value.isoformat()


def _normalize_timestamp(value: Any) -> datetime:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        ts = ts.tz_localize(UTC)
    else:
        ts = ts.tz_convert(UTC)
    return ts.to_pydatetime()


def _history_market_date_us(value: Any) -> str:
    return to_us_eastern(_normalize_timestamp(value)).date().isoformat()


def _to_float(value: Any) -> float:
    return float(0 if value is None else value)


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _extract_first_date(values: Any) -> date | None:
    for value in values:
        if value is None:
            continue
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        try:
            return pd.Timestamp(value).date()
        except (TypeError, ValueError):
            continue
    return None


def _extract_calendar_date(calendar: Any) -> str | None:
    if isinstance(calendar, pd.DataFrame) and not calendar.empty:
        for values in calendar.to_dict().values():
            value = _extract_first_date(values.values())
            if value is not None:
                return value.isoformat()
    return None
