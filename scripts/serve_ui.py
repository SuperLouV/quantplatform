"""Serve the local UI plus lightweight JSON APIs."""

from __future__ import annotations

import json
import os
import sys
from datetime import date
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from quant_platform.config import load_settings
from quant_platform.console_output import quiet_known_native_stderr
from quant_platform.services import DailyRefreshScheduler, UIDataService

SETTINGS = load_settings(PROJECT_ROOT / "config" / "settings.example.yaml")
UI_SERVICE = UIDataService(SETTINGS)
SCHEDULER = DailyRefreshScheduler(SETTINGS, project_root=PROJECT_ROOT)


class QuantPlatformHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        if _env_bool("QP_HTTP_ACCESS_LOG"):
            super().log_message(format, *args)

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
                with quiet_known_native_stderr():
                    payload = {"pools": UI_SERVICE.list_pools()}
                self._respond_json(payload)
                return
            if parsed.path == "/api/pool":
                pool_id = query.get("pool_id", [""])[0]
                with quiet_known_native_stderr():
                    payload = UI_SERVICE.load_pool_dashboard(pool_id)
                self._respond_json(payload)
                return
            if parsed.path == "/api/search":
                q = query.get("q", [""])[0]
                with quiet_known_native_stderr():
                    payload = {"results": UI_SERVICE.search(q)}
                self._respond_json(payload)
                return
            if parsed.path == "/api/snapshot":
                symbol = query.get("symbol", [""])[0].upper()
                pool_id = query.get("pool_id", [""])[0] or None
                force_refresh = query.get("force_refresh", ["0"])[0].lower() in {"1", "true", "yes"}
                with quiet_known_native_stderr():
                    payload = UI_SERVICE.load_or_fetch_snapshot(symbol, pool_id=pool_id, force_refresh=force_refresh)
                self._respond_json(payload)
                return
            if parsed.path == "/api/history":
                symbol = query.get("symbol", [""])[0].upper()
                period = query.get("period", ["6mo"])[0]
                interval = query.get("interval", ["1d"])[0]
                with quiet_known_native_stderr():
                    payload = UI_SERVICE.history(symbol, period=period, interval=interval)
                self._respond_json(payload)
                return
            if parsed.path == "/api/analysis":
                symbol = query.get("symbol", [""])[0].upper()
                pool_id = query.get("pool_id", [""])[0] or None
                with quiet_known_native_stderr():
                    payload = UI_SERVICE.analysis(symbol, pool_id=pool_id)
                self._respond_json(payload)
                return
            if parsed.path == "/api/scanner":
                pool_id = query.get("pool_id", ["default_core"])[0] or "default_core"
                with quiet_known_native_stderr():
                    payload = UI_SERVICE.scanner(pool_id)
                self._respond_json(payload)
                return
            if parsed.path == "/api/events/market":
                start = _optional_date(query.get("from", [""])[0])
                end = _optional_date(query.get("to", [""])[0])
                with quiet_known_native_stderr():
                    payload = UI_SERVICE.market_event_calendar(start=start, end=end)
                self._respond_json(payload)
                return
            if parsed.path == "/api/scheduler":
                self._respond_json(SCHEDULER.status())
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


def _optional_date(value: str) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value)


def _env_bool(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def main() -> None:
    port = int(os.environ.get("QP_UI_PORT") or (sys.argv[1] if len(sys.argv) > 1 else "8000"))
    os.chdir(PROJECT_ROOT)
    with ThreadingHTTPServer(("", port), QuantPlatformHandler) as httpd:
        SCHEDULER.start()
        print(f"serving={PROJECT_ROOT}")
        print(f"url=http://127.0.0.1:{port}/ui/index.html")
        status = SCHEDULER.status()
        latest = status.get("latest_summary") or {}
        print(
            "scheduler="
            f"enabled={status.get('enabled')} "
            f"time_beijing={status.get('daily_refresh_time_beijing')} "
            f"last_status={status.get('state', {}).get('last_status')} "
            f"latest_market_date_us={latest.get('market_date_us')} "
            f"history_success={latest.get('history_success')} "
            f"history_empty={latest.get('history_empty')} "
            f"history_error={latest.get('history_error')}"
        )
        try:
            httpd.serve_forever()
        finally:
            SCHEDULER.stop()


if __name__ == "__main__":
    main()
