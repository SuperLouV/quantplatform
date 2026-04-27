"""Reusable market scanner for strategy candidate generation."""

from __future__ import annotations

import math

from quant_platform.screeners.models import ScanCandidate, ScanResult, ScanSignal, ScanSummary

STRATEGY_ID = "trend_momentum_v1"
MOMENTUM_RANK_WEIGHTS = {
    "ret_60d_skip5": 0.5,
    "ret_20d_skip5": 0.3,
    "ret_120d_skip5": 0.2,
}


class MarketScanner:
    def scan_snapshots(self, snapshots: list[dict[str, object]]) -> ScanResult:
        momentum_ranks = _momentum_rank_pct(snapshots)
        candidates = [
            self.scan_snapshot(snapshot, momentum_rank_pct=momentum_ranks.get(str(snapshot.get("symbol") or "")))
            for snapshot in snapshots
        ]
        candidates = sorted(candidates, key=lambda item: (-item.score, item.symbol))
        return ScanResult(summary=_summarize(candidates), candidates=candidates)

    def scan_snapshot(self, snapshot: dict[str, object], *, momentum_rank_pct: float | None = None) -> ScanCandidate:
        indicators = snapshot.get("indicators") if isinstance(snapshot.get("indicators"), dict) else {}
        assert isinstance(indicators, dict)
        price = _optional_float(snapshot.get("current_price")) or _optional_float(snapshot.get("latest_close"))
        previous_close = _optional_float(snapshot.get("previous_close"))
        change_percent = _optional_float(snapshot.get("change_percent"))
        if change_percent is None and price is not None and previous_close not in (None, 0):
            change_percent = ((price - previous_close) / previous_close) * 100

        sma20 = _optional_float(indicators.get("sma_20"))
        sma50 = _optional_float(indicators.get("sma_50"))
        sma200 = _optional_float(indicators.get("sma_200"))
        rsi14 = _optional_float(indicators.get("rsi_14"))
        macd = _optional_float(indicators.get("macd"))
        macd_signal = _optional_float(indicators.get("macd_signal"))
        volume_ratio = _optional_float(indicators.get("volume_ratio_20"))
        volume_zscore = _optional_float(indicators.get("volume_zscore_60"))
        rsi_delta_5d = _optional_float(indicators.get("rsi_14_delta_5d"))
        trend_distance = _optional_float(indicators.get("trend_distance_sma50_atr14"))
        data_quality = _scan_data_quality(snapshot, indicators)

        trend_state, trend_score, trend_signal = _scan_trend(price, sma20, sma50, sma200, trend_distance)
        momentum_state, momentum_score, momentum_signal = _scan_cross_section_momentum(momentum_rank_pct)
        rsi_state, rsi_score, rsi_signal = _scan_rsi(rsi14, rsi_delta_5d)
        macd_state, macd_score, macd_signal_item = _scan_macd(macd, macd_signal)
        volume_state, volume_score, volume_signal = _scan_volume(volume_ratio, volume_zscore)
        risk_level, risk_penalty, risk_signal = _scan_risk(snapshot, data_quality)

        score = max(0, min(100, 30 + momentum_score + trend_score + rsi_score + macd_score + volume_score - risk_penalty))
        action = _scan_action(score, risk_level, data_quality)
        signals = [momentum_signal, trend_signal, rsi_signal, macd_signal_item, volume_signal, risk_signal]

        return ScanCandidate(
            strategy_id=STRATEGY_ID,
            symbol=str(snapshot.get("symbol") or ""),
            company_name=_optional_str(snapshot.get("company_name_zh") or snapshot.get("company_name")),
            price=price,
            change_percent=change_percent,
            latest_history_date_us=_optional_str(snapshot.get("latest_history_date_us")),
            snapshot_refreshed_at_beijing=_optional_str(snapshot.get("snapshot_refreshed_at_beijing")),
            score=round(score),
            action=action,
            risk_level=risk_level,
            trend_state=trend_state,
            rsi_state=rsi_state,
            macd_state=macd_state,
            volume_state=volume_state,
            data_quality=data_quality,
            momentum_rank_pct=momentum_rank_pct,
            confidence=round(score),
            market_regime="not_evaluated",
            signals=signals,
        )


def _summarize(candidates: list[ScanCandidate]) -> ScanSummary:
    return ScanSummary(
        total=len(candidates),
        candidate_buy=sum(1 for item in candidates if item.action == "候选买入"),
        watch=sum(1 for item in candidates if item.action == "继续观察"),
        risk_avoid=sum(1 for item in candidates if item.action == "风险回避"),
        insufficient_data=sum(1 for item in candidates if item.action == "数据不足"),
        high_risk=sum(1 for item in candidates if item.risk_level == "高"),
        medium_risk=sum(1 for item in candidates if item.risk_level == "中"),
        low_risk=sum(1 for item in candidates if item.risk_level == "低"),
    )


def _momentum_rank_pct(snapshots: list[dict[str, object]]) -> dict[str, float]:
    values_by_symbol: dict[str, dict[str, float]] = {}
    for snapshot in snapshots:
        symbol = str(snapshot.get("symbol") or "")
        indicators = snapshot.get("indicators") if isinstance(snapshot.get("indicators"), dict) else {}
        if not symbol or not isinstance(indicators, dict):
            continue

        values: dict[str, float] = {}
        for key in MOMENTUM_RANK_WEIGHTS:
            value = _optional_float(indicators.get(key))
            if value is not None:
                values[key] = value
        if values:
            values_by_symbol[symbol] = values

    percentile_by_symbol: dict[str, dict[str, float]] = {symbol: {} for symbol in values_by_symbol}
    for key in MOMENTUM_RANK_WEIGHTS:
        ranked_values = [(symbol, values[key]) for symbol, values in values_by_symbol.items() if key in values]
        if len(ranked_values) < 2:
            continue
        for symbol, rank_pct in _percentile_ranks(ranked_values).items():
            percentile_by_symbol[symbol][key] = rank_pct

    momentum_ranks: dict[str, float] = {}
    for symbol, ranks in percentile_by_symbol.items():
        weight_total = sum(weight for key, weight in MOMENTUM_RANK_WEIGHTS.items() if key in ranks)
        if weight_total <= 0:
            continue
        weighted_rank = sum(ranks[key] * MOMENTUM_RANK_WEIGHTS[key] for key in ranks) / weight_total
        momentum_ranks[symbol] = round(weighted_rank, 2)
    return momentum_ranks


def _percentile_ranks(values: list[tuple[str, float]]) -> dict[str, float]:
    if len(values) == 1:
        return {values[0][0]: 100.0}

    sorted_values = sorted(values, key=lambda item: item[1])
    ranks: dict[str, float] = {}
    start = 0
    last_index = len(sorted_values) - 1
    while start < len(sorted_values):
        end = start
        current_value = sorted_values[start][1]
        while end + 1 < len(sorted_values) and sorted_values[end + 1][1] == current_value:
            end += 1

        average_index = (start + end) / 2
        rank_pct = (average_index / last_index) * 100
        for index in range(start, end + 1):
            ranks[sorted_values[index][0]] = rank_pct
        start = end + 1
    return ranks


def _scan_data_quality(snapshot: dict[str, object], indicators: dict[str, object]) -> str:
    if not snapshot.get("latest_history_date_us"):
        return "缺行情日期"
    usable = any(_optional_float(indicators.get(key)) is not None for key in ("sma_20", "sma_50", "rsi_14", "macd"))
    if not usable:
        return "指标不足"
    return "正常"


def _scan_cross_section_momentum(rank_pct: float | None) -> tuple[str, int, ScanSignal]:
    if rank_pct is None:
        return "未排名", 0, ScanSignal("cross_section_momentum", "neutral", 0, "未排名", "截面动量排名数据不足")
    if rank_pct >= 80:
        return "Top20%", 22, ScanSignal("cross_section_momentum", "bullish", 22, "Top20%", "截面动量处于池内前 20%", {"momentum_rank_pct": rank_pct})
    if rank_pct >= 50:
        return "Top50%", 8, ScanSignal("cross_section_momentum", "neutral", 8, "Top50%", "截面动量处于池内前 50%", {"momentum_rank_pct": rank_pct})
    return "后50%", -18, ScanSignal("cross_section_momentum", "bearish", 18, "后50%", "截面动量处于池内后 50%", {"momentum_rank_pct": rank_pct})


def _scan_trend(
    price: float | None,
    sma20: float | None,
    sma50: float | None,
    sma200: float | None,
    trend_distance: float | None,
) -> tuple[str, int, ScanSignal]:
    if price is None or sma20 is None or sma50 is None:
        return "数据不足", -18, ScanSignal("trend", "neutral", 18, "数据不足", "趋势数据不足")
    if trend_distance is not None and trend_distance < -1:
        return "显著弱势", -20, ScanSignal("trend", "bearish", 20, "显著弱势", "价格低于 SMA50 超过 1 个 ATR", {"price": price, "sma50": sma50, "trend_distance_sma50_atr14": trend_distance})
    if sma200 is not None and price > sma20 > sma50 > sma200:
        return "多头排列", 18, ScanSignal("trend", "bullish", 18, "多头排列", "价格和均线呈多头排列", {"price": price, "sma20": sma20, "sma50": sma50, "sma200": sma200, "trend_distance_sma50_atr14": trend_distance})
    if price > sma20 and sma20 >= sma50:
        return "偏强", 12, ScanSignal("trend", "bullish", 12, "偏强", "价格站上短中期均线", {"price": price, "sma20": sma20, "sma50": sma50, "trend_distance_sma50_atr14": trend_distance})
    if price < sma20 and sma20 < sma50:
        return "转弱", -12, ScanSignal("trend", "bearish", 12, "转弱", "价格跌破短期均线且短线弱于中期", {"price": price, "sma20": sma20, "sma50": sma50, "trend_distance_sma50_atr14": trend_distance})
    return "震荡", 0, ScanSignal("trend", "neutral", 0, "震荡", "趋势方向暂不明确", {"price": price, "sma20": sma20, "sma50": sma50, "sma200": sma200, "trend_distance_sma50_atr14": trend_distance})


def _scan_rsi(rsi14: float | None, rsi_delta_5d: float | None) -> tuple[str, int, ScanSignal]:
    if rsi14 is None:
        return "数据不足", -10, ScanSignal("momentum", "neutral", 10, "数据不足", "RSI 数据不足")
    if 45 <= rsi14 <= 68 and (rsi_delta_5d is None or rsi_delta_5d > 0):
        return "健康", 8, ScanSignal("momentum", "bullish", 8, "健康", "RSI 处于健康区间且动量未衰减", {"rsi14": rsi14, "rsi_delta_5d": rsi_delta_5d})
    if 30 <= rsi14 < 45:
        return "修复", 4, ScanSignal("momentum", "bullish", 4, "修复", "RSI 从弱势区间修复中", {"rsi14": rsi14, "rsi_delta_5d": rsi_delta_5d})
    if rsi14 < 30:
        return "超跌", -2, ScanSignal("momentum", "neutral", 2, "超跌", "RSI 低于 30，可能超跌但仍需确认", {"rsi14": rsi14})
    if rsi14 > 80:
        return "过热", -14, ScanSignal("momentum", "bearish", 14, "过热", "RSI 高位严重过热", {"rsi14": rsi14, "rsi_delta_5d": rsi_delta_5d})
    return "偏热", -2, ScanSignal("momentum", "neutral", 2, "偏热", "RSI 偏高，追涨风险上升", {"rsi14": rsi14, "rsi_delta_5d": rsi_delta_5d})


def _scan_macd(macd: float | None, signal: float | None) -> tuple[str, int, ScanSignal]:
    if macd is None or signal is None:
        return "数据不足", -8, ScanSignal("macd", "neutral", 8, "数据不足", "MACD 数据不足")
    if macd > signal:
        return "偏多", 10, ScanSignal("macd", "bullish", 10, "偏多", "MACD 在 Signal 上方", {"macd": macd, "signal": signal})
    if macd < signal:
        return "偏弱", -8, ScanSignal("macd", "bearish", 8, "偏弱", "MACD 在 Signal 下方", {"macd": macd, "signal": signal})
    return "中性", 0, ScanSignal("macd", "neutral", 0, "中性", "MACD 与 Signal 接近", {"macd": macd, "signal": signal})


def _scan_volume(volume_ratio: float | None, volume_zscore: float | None) -> tuple[str, int, ScanSignal]:
    if volume_ratio is None and volume_zscore is None:
        return "数据不足", -4, ScanSignal("volume", "neutral", 4, "数据不足", "成交量指标不足")
    if volume_zscore is not None and volume_zscore >= 0.5:
        return "资金参与", 8, ScanSignal("volume", "bullish", 8, "资金参与", "成交量 z-score 高于 0.5", {"volume_ratio_20": volume_ratio, "volume_zscore_60": volume_zscore})
    if volume_ratio is not None and volume_ratio >= 1.8:
        return "明显放量", 6, ScanSignal("volume", "bullish", 6, "明显放量", "成交量明显高于 20 日均量", {"volume_ratio_20": volume_ratio, "volume_zscore_60": volume_zscore})
    if volume_ratio is not None and volume_ratio >= 1.2:
        return "温和放量", 5, ScanSignal("volume", "bullish", 5, "温和放量", "成交量温和放大", {"volume_ratio_20": volume_ratio})
    if volume_ratio is not None and volume_ratio < 0.7:
        return "缩量", -2, ScanSignal("volume", "neutral", 2, "缩量", "成交量低于近期均量", {"volume_ratio_20": volume_ratio})
    return "正常", 0, ScanSignal("volume", "neutral", 0, "正常", "成交量接近近期均值", {"volume_ratio_20": volume_ratio, "volume_zscore_60": volume_zscore})


def _scan_risk(snapshot: dict[str, object], data_quality: str) -> tuple[str, int, ScanSignal]:
    if data_quality != "正常":
        return "高", 28, ScanSignal("risk", "bearish", 28, "高", f"数据状态：{data_quality}", {"data_quality": data_quality})
    reasons = snapshot.get("screening_reasons")
    reason_text = " ".join(str(item) for item in reasons) if isinstance(reasons, list) else ""
    if "stale_bars" in reason_text or "future_bars" in reason_text or "error" in reason_text:
        return "高", 24, ScanSignal("risk", "bearish", 24, "高", "本地数据质量存在风险提示")
    if snapshot.get("next_earnings_date"):
        return "中", 8, ScanSignal("risk", "neutral", 8, "中", "存在财报日期，需确认事件风险", {"next_earnings_date": _optional_str(snapshot.get("next_earnings_date"))})
    return "低", 0, ScanSignal("risk", "neutral", 0, "低", "未发现明显数据或事件风险")


def _scan_action(score: float, risk_level: str, data_quality: str) -> str:
    if data_quality != "正常":
        return "数据不足"
    if risk_level == "高":
        return "风险回避"
    if score >= 72:
        return "候选买入"
    return "继续观察"


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(result):
        return None
    return result


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)
