"""Extract option quote rows from OCR text or screenshots."""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import date
from importlib.util import find_spec
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from quant_platform.clients.yfinance import YFinanceClient


@dataclass(slots=True)
class ExtractedOptionQuote:
    option_type: str
    strike: float
    expiration: date
    bid: float | None = None
    ask: float | None = None
    source_line: str = ""
    confidence_notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["expiration"] = self.expiration.isoformat()
        return payload


@dataclass(slots=True)
class OptionScreenshotExtraction:
    source: str
    text: str
    contracts: list[ExtractedOptionQuote]
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "text": self.text,
            "contracts": [contract.to_dict() for contract in self.contracts],
            "warnings": self.warnings,
        }


def extract_option_quotes_from_text(text: str, *, default_expiration: date | None = None) -> OptionScreenshotExtraction:
    contracts: list[ExtractedOptionQuote] = []
    warnings: list[str] = []
    active_expiration = default_expiration
    active_type: str | None = None
    for raw_line in text.splitlines():
        line = _normalize_line(raw_line)
        if not line:
            continue
        expiry = _parse_expiration(line)
        if expiry:
            active_expiration = expiry
        detected_type = _parse_option_type(line)
        if detected_type:
            active_type = detected_type
        strike = _parse_strike(line)
        bid, ask = _parse_bid_ask(line)
        if strike is None or active_expiration is None or active_type is None:
            continue
        if bid is None and ask is None:
            continue
        notes = []
        if _parse_expiration(line) is None:
            notes.append("到期日来自前文上下文。")
        if _parse_option_type(line) is None:
            notes.append("期权方向来自前文上下文。")
        contracts.append(
            ExtractedOptionQuote(
                option_type=active_type,
                strike=strike,
                expiration=active_expiration,
                bid=bid,
                ask=ask,
                source_line=raw_line.strip(),
                confidence_notes=notes,
            )
        )
    if not contracts:
        warnings.append("未从截图文字中解析到 strike / bid / ask / expiry 的完整组合。")
    return OptionScreenshotExtraction(source="text", text=text, contracts=contracts, warnings=warnings)


def extract_option_quotes_from_image(path: str | Path) -> OptionScreenshotExtraction:
    image_path = Path(path)
    text = _ocr_image(image_path)
    extraction = extract_option_quotes_from_text(text)
    extraction.source = str(image_path)
    return extraction


def cross_validate_with_yfinance(
    *,
    symbol: str,
    contracts: list[ExtractedOptionQuote],
    client: "YFinanceClient",
    max_price_diff_pct: float = 15.0,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    chains: dict[date, dict[str, list[dict[str, Any]]]] = {}
    for contract in contracts:
        chain = chains.setdefault(contract.expiration, client.fetch_option_chain(symbol, contract.expiration))
        rows = chain.get("calls" if contract.option_type == "call" else "puts", [])
        match = _find_strike(rows, contract.strike)
        status = "missing_in_yfinance"
        warnings: list[str] = []
        if match:
            yf_bid = _optional_float(match.get("bid"))
            yf_ask = _optional_float(match.get("ask"))
            status = "matched"
            for label, extracted, reference in (("bid", contract.bid, yf_bid), ("ask", contract.ask, yf_ask)):
                if extracted is None or reference in (None, 0):
                    continue
                diff_pct = abs(extracted - reference) / reference * 100
                if diff_pct > max_price_diff_pct:
                    status = "price_mismatch"
                    warnings.append(f"{label} 与 yfinance 差异 {diff_pct:.1f}%，需要人工核对。")
        results.append(
            {
                "extracted": contract.to_dict(),
                "status": status,
                "yfinance": match,
                "warnings": warnings,
            }
        )
    return results


def _ocr_image(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(path)
    if find_spec("pytesseract") is not None:
        import pytesseract  # type: ignore[import-not-found]
        from PIL import Image  # type: ignore[import-not-found]

        return str(pytesseract.image_to_string(Image.open(path)))
    binary = shutil.which("tesseract")
    if binary:
        process = subprocess.run(
            [binary, str(path), "stdout"],
            check=True,
            text=True,
            capture_output=True,
        )
        return process.stdout
    raise RuntimeError("No OCR backend found. Install pytesseract/Pillow or the tesseract CLI.")


def _normalize_line(line: str) -> str:
    return (
        line.replace("｜", "|")
        .replace("—", "-")
        .replace("–", "-")
        .replace("买", "bid")
        .replace("卖", "ask")
        .strip()
    )


def _parse_expiration(line: str) -> date | None:
    patterns = [
        r"(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})",
        r"(\d{1,2})[-/.](\d{1,2})[-/.](20\d{2})",
    ]
    for pattern in patterns:
        match = re.search(pattern, line)
        if not match:
            continue
        groups = match.groups()
        if len(groups[0]) == 4:
            year, month, day = groups
        else:
            month, day, year = groups
        try:
            return date(int(year), int(month), int(day))
        except ValueError:
            continue
    return None


def _parse_option_type(line: str) -> str | None:
    lower = line.lower()
    if re.search(r"\b(call|covered call|认购)\b", lower):
        return "call"
    if re.search(r"\b(put|cash secured put|认沽)\b", lower):
        return "put"
    return None


def _parse_strike(line: str) -> float | None:
    patterns = [
        r"\bstrike\s*[:=]?\s*(\d+(?:\.\d+)?)",
        r"\b行权价\s*[:=]?\s*(\d+(?:\.\d+)?)",
    ]
    for pattern in patterns:
        match = re.search(pattern, line, flags=re.IGNORECASE)
        if match:
            return float(match.group(1))
    clean = _strip_dates(line)
    numbers = [float(value) for value in re.findall(r"(?<!\d)(\d{1,5}(?:\.\d+)?)(?!\d)", clean)]
    prices = [number for number in numbers if number >= 1]
    return prices[0] if prices else None


def _parse_bid_ask(line: str) -> tuple[float | None, float | None]:
    bid = _parse_labeled_price(line, "bid")
    ask = _parse_labeled_price(line, "ask")
    if bid is not None or ask is not None:
        return bid, ask
    clean = _strip_dates(line)
    numbers = [float(value) for value in re.findall(r"(?<!\d)(\d+(?:\.\d+)?)(?!\d)", clean)]
    small_prices = [number for number in numbers if 0 <= number <= 100]
    if len(small_prices) >= 3:
        return small_prices[-2], small_prices[-1]
    return None, None


def _parse_labeled_price(line: str, label: str) -> float | None:
    match = re.search(rf"\b{label}\s*[:=]?\s*(\d+(?:\.\d+)?)", line, flags=re.IGNORECASE)
    return float(match.group(1)) if match else None


def _strip_dates(line: str) -> str:
    line = re.sub(r"20\d{2}[-/.]\d{1,2}[-/.]\d{1,2}", " ", line)
    return re.sub(r"\d{1,2}[-/.]\d{1,2}[-/.]20\d{2}", " ", line)


def _find_strike(rows: list[dict[str, Any]], strike: float) -> dict[str, Any] | None:
    for row in rows:
        row_strike = _optional_float(row.get("strike"))
        if row_strike is not None and abs(row_strike - strike) < 0.001:
            return row
    return None


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
