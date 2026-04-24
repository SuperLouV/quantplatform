"""Serve the local UI plus lightweight JSON APIs."""

from __future__ import annotations

import json
import os
import sys
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from quant_platform.config import load_settings
from quant_platform.services import UIDataService

SETTINGS = load_settings(PROJECT_ROOT / "config" / "settings.example.yaml")
UI_SERVICE = UIDataService(SETTINGS)


class QuantPlatformHandler(SimpleHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            self._handle_api(parsed)
            return
        super().do_GET()

    def _handle_api(self, parsed) -> None:
        query = parse_qs(parsed.query)
        try:
            if parsed.path == "/api/pools":
                self._respond_json({"pools": UI_SERVICE.list_pools()})
                return
            if parsed.path == "/api/pool":
                pool_id = query.get("pool_id", [""])[0]
                self._respond_json(UI_SERVICE.load_pool_dashboard(pool_id))
                return
            if parsed.path == "/api/search":
                q = query.get("q", [""])[0]
                self._respond_json({"results": UI_SERVICE.search(q)})
                return
            if parsed.path == "/api/snapshot":
                symbol = query.get("symbol", [""])[0].upper()
                pool_id = query.get("pool_id", [""])[0] or None
                self._respond_json(UI_SERVICE.load_or_fetch_snapshot(symbol, pool_id=pool_id))
                return
            if parsed.path == "/api/history":
                symbol = query.get("symbol", [""])[0].upper()
                period = query.get("period", ["6mo"])[0]
                interval = query.get("interval", ["1d"])[0]
                self._respond_json(UI_SERVICE.history(symbol, period=period, interval=interval))
                return
            if parsed.path == "/api/analysis":
                symbol = query.get("symbol", [""])[0].upper()
                pool_id = query.get("pool_id", [""])[0] or None
                self._respond_json(UI_SERVICE.analysis(symbol, pool_id=pool_id))
                return
            self.send_error(HTTPStatus.NOT_FOUND, "Unknown API endpoint")
        except Exception as exc:  # noqa: BLE001
            self._respond_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def _respond_json(self, payload: dict[str, object], status: HTTPStatus = HTTPStatus.OK) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def main() -> None:
    port = 8000
    os.chdir(PROJECT_ROOT)
    with ThreadingHTTPServer(("", port), QuantPlatformHandler) as httpd:
        print(f"serving={PROJECT_ROOT}")
        print(f"url=http://127.0.0.1:{port}/ui/index.html")
        httpd.serve_forever()


if __name__ == "__main__":
    main()
