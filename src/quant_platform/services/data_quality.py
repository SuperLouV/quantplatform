"""Data quality checks shared by ingestion, snapshots, and reports."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from quant_platform.core.models import Bar


@dataclass(slots=True)
class DataQualityIssue:
    severity: str
    code: str
    message: str


@dataclass(slots=True)
class DataQualityReport:
    symbol: str
    status: str
    issues: list[DataQualityIssue] = field(default_factory=list)

    @property
    def messages(self) -> list[str]:
        return [f"{issue.severity}:{issue.code}:{issue.message}" for issue in self.issues]

    @property
    def has_errors(self) -> bool:
        return any(issue.severity == "error" for issue in self.issues)


def validate_bars(symbol: str, bars: list[Bar], *, min_rows: int = 50) -> DataQualityReport:
    issues: list[DataQualityIssue] = []

    if not bars:
        issues.append(_issue("error", "no_bars", "历史日线为空。"))
        return _report(symbol, issues)

    if len(bars) < min_rows:
        issues.append(_issue("warning", "insufficient_history", f"历史日线少于 {min_rows} 条。"))

    previous_close: float | None = None
    for bar in bars:
        if not _is_positive(bar.open) or not _is_positive(bar.high) or not _is_positive(bar.low) or not _is_positive(bar.close):
            issues.append(_issue("error", "invalid_price", f"{bar.timestamp.date()} 存在非正价格。"))
            break
        if bar.high < max(bar.open, bar.close, bar.low):
            issues.append(_issue("error", "invalid_high_low", f"{bar.timestamp.date()} high/low 关系异常。"))
            break
        if bar.low > min(bar.open, bar.close, bar.high):
            issues.append(_issue("error", "invalid_high_low", f"{bar.timestamp.date()} high/low 关系异常。"))
            break
        if bar.volume <= 0:
            issues.append(_issue("warning", "zero_volume", f"{bar.timestamp.date()} 成交量为 0。"))
            break
        if previous_close is not None and previous_close > 0:
            move = abs(bar.close - previous_close) / previous_close
            if move >= 0.5:
                issues.append(_issue("warning", "large_price_move", f"{bar.timestamp.date()} 单日涨跌幅超过 50%。"))
                break
        previous_close = bar.close

    return _report(symbol, issues)


def validate_quote_snapshot(symbol: str, quote: dict[str, Any]) -> DataQualityReport:
    issues: list[DataQualityIssue] = []

    latest_close = _optional_float(quote.get("latest_close"))
    previous_close = _optional_float(quote.get("previous_close"))
    latest_volume = _optional_float(quote.get("latest_volume"))

    if not _is_positive(latest_close):
        issues.append(_issue("error", "missing_latest_close", "缺少有效最新价格。"))
    if previous_close is not None and previous_close <= 0:
        issues.append(_issue("warning", "invalid_previous_close", "前收盘价无效。"))
    if latest_volume is not None and latest_volume <= 0:
        issues.append(_issue("warning", "zero_latest_volume", "最新成交量为 0。"))
    if not quote.get("sector"):
        issues.append(_issue("warning", "missing_sector", "缺少行业/板块信息。"))
    if not quote.get("currency"):
        issues.append(_issue("warning", "missing_currency", "缺少币种信息。"))

    return _report(symbol, issues)


def summarize_quality(reports: list[DataQualityReport]) -> dict[str, int]:
    summary = {"ok": 0, "warning": 0, "error": 0}
    for report in reports:
        summary[report.status] = summary.get(report.status, 0) + 1
    return summary


def _report(symbol: str, issues: list[DataQualityIssue]) -> DataQualityReport:
    if any(issue.severity == "error" for issue in issues):
        status = "error"
    elif issues:
        status = "warning"
    else:
        status = "ok"
    return DataQualityReport(symbol=symbol, status=status, issues=issues)


def _issue(severity: str, code: str, message: str) -> DataQualityIssue:
    return DataQualityIssue(severity=severity, code=code, message=message)


def _is_positive(value: float | None) -> bool:
    return value is not None and math.isfinite(value) and value > 0


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(result):
        return None
    return result
