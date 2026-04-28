"""Local market overview built from processed daily bars."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, date
from pathlib import Path

import pandas as pd

from quant_platform.config import Settings
from quant_platform.indicators import IndicatorEngine
from quant_platform.services.bootstrap import bootstrap_local_state
from quant_platform.services.operation_log import OperationLogger, operation_log_root
from quant_platform.time_utils import to_us_eastern

INDEX_SYMBOLS = ("SPY", "QQQ", "DIA", "^VIX")
SECTOR_ETFS = {
    "XLK": "科技",
    "XLF": "金融",
    "XLV": "医疗",
    "XLY": "可选消费",
    "XLC": "通信服务",
    "XLI": "工业",
    "XLE": "能源",
    "XLP": "必需消费",
    "XLU": "公用事业",
    "XLB": "材料",
    "XLRE": "房地产",
}
MARKET_OVERVIEW_SYMBOLS = (*INDEX_SYMBOLS, *SECTOR_ETFS.keys())


@dataclass(slots=True)
class MarketInstrumentState:
    symbol: str
    name: str
    latest_date_us: str | None
    close: float | None
    change_1d_pct: float | None
    change_5d_pct: float | None
    change_20d_pct: float | None
    sma50: float | None
    distance_sma50_pct: float | None
    rsi14: float | None
    trend_state: str
    data_status: str


@dataclass(slots=True)
class MarketOverview:
    market_date_us: str
    generated_at_beijing: str
    indexes: list[MarketInstrumentState]
    sectors: list[MarketInstrumentState]
    summary: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return {
            "market_date_us": self.market_date_us,
            "generated_at_beijing": self.generated_at_beijing,
            "indexes": [asdict(item) for item in self.indexes],
            "sectors": [asdict(item) for item in self.sectors],
            "summary": self.summary,
        }


class MarketOverviewService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.artifacts = bootstrap_local_state(settings)
        self.indicator_engine = IndicatorEngine()
        self.logger = OperationLogger(operation_log_root(settings), "market_overview")

    def build(self, *, market_date_us: date, generated_at_beijing: str) -> MarketOverview:
        self.logger.info("market_overview.build.start", market_date_us=market_date_us.isoformat())
        indexes = [self._instrument_state(symbol, symbol, market_date_us=market_date_us) for symbol in INDEX_SYMBOLS]
        sectors = [
            self._instrument_state(symbol, f"{symbol} {name}", market_date_us=market_date_us)
            for symbol, name in SECTOR_ETFS.items()
        ]
        summary = _summarize_overview(indexes, sectors)
        self.logger.info(
            "market_overview.build.success",
            market_date_us=market_date_us.isoformat(),
            indexes=len(indexes),
            sectors=len(sectors),
            summary=summary,
        )
        return MarketOverview(
            market_date_us=market_date_us.isoformat(),
            generated_at_beijing=generated_at_beijing,
            indexes=indexes,
            sectors=sectors,
            summary=summary,
        )

    def _instrument_state(self, symbol: str, name: str, *, market_date_us: date) -> MarketInstrumentState:
        path = self.artifacts.layout.processed_symbol_path(self.settings.data.provider, "bars", symbol)
        if not path.exists():
            return _missing_state(symbol, name, "missing_local_bars")
        try:
            frame = pd.read_parquet(path)
            if frame.empty:
                return _missing_state(symbol, name, "empty_local_bars")
            prepared = self.indicator_engine.compute(frame).series
            if prepared.empty:
                return _missing_state(symbol, name, "empty_indicators")
            latest = prepared.iloc[-1]
            previous = prepared.iloc[-2] if len(prepared.index) >= 2 else None
            close = _optional_float(latest.get("close"))
            previous_close = _optional_float(previous.get("close")) if previous is not None else None
            sma50 = _optional_float(latest.get("sma_50"))
            rsi14 = _optional_float(latest.get("rsi_14"))
            latest_date_us = _market_date_us(latest.get("timestamp"))
            data_status = "ok"
            trend_state = _trend_state(close, sma50)
            if latest_date_us and latest_date_us < market_date_us.isoformat():
                data_status = "stale_local_bars"
                trend_state = f"数据过期：{latest_date_us}"
            return MarketInstrumentState(
                symbol=symbol,
                name=name,
                latest_date_us=latest_date_us,
                close=close,
                change_1d_pct=_pct_change(close, previous_close),
                change_5d_pct=_period_change(prepared, 5),
                change_20d_pct=_period_change(prepared, 20),
                sma50=sma50,
                distance_sma50_pct=_pct_change(close, sma50),
                rsi14=rsi14,
                trend_state=trend_state,
                data_status=data_status,
            )
        except Exception as exc:  # noqa: BLE001 - reports should degrade instead of failing on one market proxy.
            self.logger.error("market_overview.instrument.error", symbol=symbol, path=str(path), error=str(exc))
            return _missing_state(symbol, name, "error")


def _missing_state(symbol: str, name: str, status: str) -> MarketInstrumentState:
    return MarketInstrumentState(
        symbol=symbol,
        name=name,
        latest_date_us=None,
        close=None,
        change_1d_pct=None,
        change_5d_pct=None,
        change_20d_pct=None,
        sma50=None,
        distance_sma50_pct=None,
        rsi14=None,
        trend_state="数据不足",
        data_status=status,
    )


def _summarize_overview(
    indexes: list[MarketInstrumentState],
    sectors: list[MarketInstrumentState],
) -> dict[str, object]:
    usable_indexes = [item for item in indexes if item.data_status == "ok"]
    usable_sectors = [item for item in sectors if item.data_status == "ok"]
    sectors_sorted = sorted(
        usable_sectors,
        key=lambda item: item.change_1d_pct if item.change_1d_pct is not None else -999,
        reverse=True,
    )
    risk_proxy = next((item for item in indexes if item.symbol == "SPY"), None)
    qqq = next((item for item in indexes if item.symbol == "QQQ"), None)
    vix = next((item for item in indexes if item.symbol == "^VIX"), None)
    return {
        "risk_state": _risk_state(risk_proxy, qqq, vix),
        "vix_state": _vix_state(vix),
        "vix_close": vix.close if vix and vix.data_status == "ok" else None,
        "index_data_count": len(usable_indexes),
        "sector_data_count": len(usable_sectors),
        "missing_indexes": [item.symbol for item in indexes if item.data_status != "ok"],
        "missing_sectors": [item.symbol for item in sectors if item.data_status != "ok"],
        "top_sectors": [item.symbol for item in sectors_sorted[:3]],
        "weak_sectors": [item.symbol for item in sectors_sorted[-3:]],
    }


def _risk_state(
    spy: MarketInstrumentState | None,
    qqq: MarketInstrumentState | None,
    vix: MarketInstrumentState | None,
) -> str:
    if spy is None or spy.data_status != "ok":
        return "Neutral：SPY 数据不足"
    if vix and vix.data_status == "ok" and vix.close is not None and vix.close >= 25:
        return "Risk Off：VIX 高于 25，市场波动风险较高"
    if spy.distance_sma50_pct is not None and spy.distance_sma50_pct < -2:
        return "Risk Off：SPY 明显低于 SMA50"
    if vix and vix.data_status == "ok" and vix.close is not None and vix.close >= 20:
        return "Neutral：VIX 高于 20，追涨需要降风险"
    if qqq and qqq.data_status == "ok" and qqq.distance_sma50_pct is not None and qqq.distance_sma50_pct < -2:
        return "Neutral：QQQ 低于 SMA50，成长股风险偏弱"
    if spy.distance_sma50_pct is not None and spy.distance_sma50_pct >= 0:
        return "Risk On：SPY 位于 SMA50 上方"
    return "Neutral：市场趋势不明确"


def _vix_state(vix: MarketInstrumentState | None) -> str:
    if vix is None or vix.data_status != "ok" or vix.close is None:
        return "VIX 数据不足"
    if vix.close >= 30:
        return "恐慌区间：波动显著升高"
    if vix.close >= 25:
        return "高风险区间：需要控制仓位"
    if vix.close >= 20:
        return "警戒区间：不适合激进追涨"
    if vix.close < 13:
        return "低波动区间：警惕过度乐观"
    return "正常区间：市场波动可控"


def _trend_state(close: float | None, sma50: float | None) -> str:
    if close is None or sma50 is None:
        return "数据不足"
    if close > sma50:
        return "强于 SMA50"
    if close < sma50:
        return "弱于 SMA50"
    return "贴近 SMA50"


def _period_change(frame: pd.DataFrame, periods: int) -> float | None:
    if len(frame.index) <= periods:
        return None
    close = _optional_float(frame.iloc[-1].get("close"))
    base = _optional_float(frame.iloc[-1 - periods].get("close"))
    return _pct_change(close, base)


def _pct_change(current: float | None, previous: float | None) -> float | None:
    if current is None or previous in (None, 0):
        return None
    return ((current - previous) / previous) * 100


def _market_date_us(value: object) -> str | None:
    if value is None:
        return None
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize(UTC)
    return to_us_eastern(timestamp.to_pydatetime()).date().isoformat()


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
