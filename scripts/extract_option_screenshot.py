"""Extract option rows from OCR text or an image screenshot."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from quant_platform.config import load_settings
from quant_platform.options.screenshot_parser import (
    cross_validate_with_yfinance,
    extract_option_quotes_from_image,
    extract_option_quotes_from_text,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract option quote data from screenshot OCR text or image.")
    parser.add_argument("--image", help="Screenshot image path. Requires pytesseract/Pillow or tesseract CLI.")
    parser.add_argument("--text-file", help="Text file containing OCR output.")
    parser.add_argument("--symbol", help="Cross-validate parsed rows against yfinance option chain for this symbol.")
    args = parser.parse_args()
    if not args.image and not args.text_file:
        parser.error("Provide --image or --text-file.")

    if args.image:
        extraction = extract_option_quotes_from_image(args.image)
    else:
        text = Path(args.text_file).read_text(encoding="utf-8")
        extraction = extract_option_quotes_from_text(text)

    payload = extraction.to_dict()
    if args.symbol:
        from quant_platform.clients.yfinance import YFinanceClient

        settings = load_settings(PROJECT_ROOT / "config" / "settings.example.yaml")
        payload["yfinance_validation"] = cross_validate_with_yfinance(
            symbol=args.symbol.upper(),
            contracts=extraction.contracts,
            client=YFinanceClient.from_data_config(settings.data),
        )
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
