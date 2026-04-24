"""Structured analysis helpers for snapshot-level reasoning."""

from __future__ import annotations

from datetime import UTC, datetime

from quant_platform.core.product_models import AIAnalysisResult, StockPoolSnapshot, StockSnapshot


class AIAnalysisService:
    """Prepare structured AI analysis outputs without binding to a specific model provider yet."""

    def create_placeholder_for_snapshot(self, snapshot: StockSnapshot) -> AIAnalysisResult:
        key_points = [
            f"screening_status={snapshot.screening_status}",
            f"latest_close={snapshot.latest_close}",
            f"pool_count={len(snapshot.pool_ids)}",
        ]
        warnings = list(snapshot.screening_reasons)
        return AIAnalysisResult(
            analysis_id=f"stock:{snapshot.symbol}:{_utcnow().strftime('%Y%m%dT%H%M%SZ')}",
            target_type="stock_snapshot",
            target_id=snapshot.symbol,
            risk_level=_infer_risk(snapshot.screening_status),
            recommendation=_infer_recommendation(snapshot.screening_status),
            summary="Placeholder analysis result. Replace with model-backed interpretation later.",
            key_points=key_points,
            warnings=warnings,
            generated_at=_utcnow(),
        )

    def create_placeholder_for_pool(self, pool: StockPoolSnapshot) -> AIAnalysisResult:
        return AIAnalysisResult(
            analysis_id=f"pool:{pool.pool_id}:{_utcnow().strftime('%Y%m%dT%H%M%SZ')}",
            target_type="stock_pool",
            target_id=pool.pool_id,
            risk_level="unknown",
            recommendation="review",
            summary="Placeholder pool-level analysis result. Replace with model-backed interpretation later.",
            key_points=[
                f"member_count={len(pool.members)}",
                f"pool_type={pool.pool_type}",
                f"source={pool.source}",
            ],
            warnings=[],
            generated_at=_utcnow(),
        )

    def create_simple_market_analysis(
        self,
        snapshot: StockSnapshot,
        history_points: list[dict[str, object]],
    ) -> AIAnalysisResult:
        closes = [
            float(point["close"])
            for point in history_points
            if point.get("close") is not None
        ]

        latest_close = snapshot.latest_close
        sma20 = _simple_average(closes[-20:]) if len(closes) >= 20 else None
        sma50 = _simple_average(closes[-50:]) if len(closes) >= 50 else None
        return_20d = _return_rate(closes[-21], closes[-1]) if len(closes) >= 21 else None
        volatility_20d = _volatility(closes[-21:]) if len(closes) >= 21 else None

        trend_score = 0
        if latest_close is not None and sma20 is not None and latest_close > sma20:
            trend_score += 1
        if sma20 is not None and sma50 is not None and sma20 > sma50:
            trend_score += 1
        if return_20d is not None and return_20d > 0:
            trend_score += 1

        risk_score = 0
        warnings: list[str] = []
        if volatility_20d is not None and volatility_20d > 0.035:
            risk_score += 1
            warnings.append("近20个交易日波动偏高。")
        if snapshot.avg_dollar_volume is not None and snapshot.avg_dollar_volume < 20_000_000:
            risk_score += 1
            warnings.append("平均成交额偏低，流动性一般。")
        if snapshot.next_earnings_date:
            warnings.append("存在临近财报事件，需留意事件风险。")

        if trend_score >= 3:
            recommendation = "buy_watch"
            summary = "价格结构偏强，适合作为重点跟踪的候选买点。"
        elif trend_score == 2:
            recommendation = "watch"
            summary = "趋势中性偏强，适合继续观察，不建议追高。"
        else:
            recommendation = "avoid"
            summary = "趋势条件不足，当前更适合等待而不是主动介入。"

        if risk_score >= 2:
            risk_level = "high"
        elif risk_score == 1:
            risk_level = "medium"
        else:
            risk_level = "low"

        key_points = [
            _format_key_point("最新价格", latest_close),
            _format_key_point("SMA20", sma20),
            _format_key_point("SMA50", sma50),
            _format_percent_point("20日涨跌幅", return_20d),
            _format_percent_point("20日波动率", volatility_20d),
        ]

        return AIAnalysisResult(
            analysis_id=f"market:{snapshot.symbol}:{_utcnow().strftime('%Y%m%dT%H%M%SZ')}",
            target_type="stock_snapshot",
            target_id=snapshot.symbol,
            risk_level=risk_level,
            recommendation=recommendation,
            summary=summary,
            key_points=[point for point in key_points if point is not None],
            warnings=warnings,
            generated_at=_utcnow(),
        )


def _infer_risk(status: str) -> str:
    if status == "passed":
        return "medium"
    if status == "pending_data":
        return "unknown"
    return "high"


def _infer_recommendation(status: str) -> str:
    if status == "passed":
        return "review"
    if status == "pending_data":
        return "collect_data"
    return "avoid"


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


def _simple_average(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _return_rate(start: float, end: float) -> float | None:
    if start in (0, None):
        return None
    return (end - start) / start


def _volatility(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    returns = []
    for index in range(1, len(values)):
        prev = values[index - 1]
        curr = values[index]
        if prev in (0, None):
            continue
        returns.append((curr - prev) / prev)
    if len(returns) < 2:
        return None
    mean = sum(returns) / len(returns)
    variance = sum((value - mean) ** 2 for value in returns) / (len(returns) - 1)
    return variance ** 0.5


def _format_key_point(label: str, value: float | None) -> str | None:
    if value is None:
        return None
    return f"{label}={value:.2f}"


def _format_percent_point(label: str, value: float | None) -> str | None:
    if value is None:
        return None
    return f"{label}={value * 100:.2f}%"
