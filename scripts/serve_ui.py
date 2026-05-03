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
from quant_platform.clients import LongbridgeCLIClient
from quant_platform.options import (
    AccountProfile,
    OptionContract,
    OptionsAssistantService,
    OptionStrategyRequest,
    SellPutScanConfig,
    StockOptionContext,
)
from quant_platform.services import DailyRefreshScheduler, UIDataService

SETTINGS = load_settings(PROJECT_ROOT / "config" / "settings.example.yaml")
UI_SERVICE = UIDataService(SETTINGS)
OPTIONS_SERVICE = OptionsAssistantService()
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

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/options/evaluate":
            self._handle_options_evaluate()
            return
        if parsed.path == "/api/options/scan-sell-put":
            self._handle_options_scan_sell_put()
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Unknown API endpoint")

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

    def _handle_options_evaluate(self) -> None:
        try:
            payload = self._read_json_body()
            request = _option_request_from_payload(payload)
            evaluation = OPTIONS_SERVICE.evaluate(request)
            response: dict[str, object] = {"evaluation": evaluation.to_dict()}
            if bool(payload.get("with_prompt")):
                response["ai_prompt"] = OPTIONS_SERVICE.build_ai_prompt(evaluation)
            self._respond_json(response)
        except Exception as exc:  # noqa: BLE001
            self._respond_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)

    def _handle_options_scan_sell_put(self) -> None:
        try:
            payload = self._read_json_body()
            with quiet_known_native_stderr():
                result = _sell_put_scan_from_payload(payload)
            self._respond_json({"scan": result.to_dict()})
        except Exception as exc:  # noqa: BLE001
            self._respond_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)

    def _read_json_body(self) -> dict[str, object]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("JSON body must be an object")
        return payload

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


def _option_request_from_payload(payload: dict[str, object]) -> OptionStrategyRequest:
    account_payload = payload.get("account") if isinstance(payload.get("account"), dict) else {}
    stock_payload = payload.get("stock") if isinstance(payload.get("stock"), dict) else {}
    contract_payload = payload.get("contract") if isinstance(payload.get("contract"), dict) else {}
    if not isinstance(account_payload, dict) or not isinstance(stock_payload, dict) or not isinstance(contract_payload, dict):
        raise ValueError("account, stock, and contract must be objects")

    strategy = str(payload.get("strategy") or "")
    symbol = str(stock_payload.get("symbol") or contract_payload.get("symbol") or payload.get("symbol") or "").upper()
    if strategy not in {"cash_secured_put", "covered_call"}:
        raise ValueError("strategy must be cash_secured_put or covered_call")
    if not symbol:
        raise ValueError("symbol is required")
    option_type = str(contract_payload.get("option_type") or "")
    if option_type not in {"put", "call"}:
        raise ValueError("contract.option_type must be put or call")

    return OptionStrategyRequest(
        strategy=strategy,  # type: ignore[arg-type]
        account=AccountProfile(
            equity=_float(account_payload.get("equity"), 5_000),
            cash=_float(account_payload.get("cash"), 5_000),
            max_cash_per_trade_pct=_float(account_payload.get("max_cash_per_trade_pct"), 0.4),
            max_loss_pct=_float(account_payload.get("max_loss_pct"), 0.5),
            allow_assignment=_bool(account_payload.get("allow_assignment"), True),
            stock_shares=int(account_payload.get("stock_shares") or 0),
            stock_cost_basis=_optional_float(account_payload.get("stock_cost_basis")),
        ),
        stock=StockOptionContext(
            symbol=symbol,
            current_price=_required_float(stock_payload.get("current_price"), "stock.current_price"),
            as_of=date.fromisoformat(str(stock_payload.get("as_of") or date.today().isoformat())),
            support_price=_optional_float(stock_payload.get("support_price")),
            resistance_price=_optional_float(stock_payload.get("resistance_price")),
            trend_state=_optional_str(stock_payload.get("trend_state")),
            rsi14=_optional_float(stock_payload.get("rsi14")),
            earnings_days=_optional_int(stock_payload.get("earnings_days")),
            market_risk_state=_optional_str(stock_payload.get("market_risk_state")),
        ),
        contract=OptionContract(
            symbol=symbol,
            option_type=option_type,  # type: ignore[arg-type]
            strike=_required_float(contract_payload.get("strike"), "contract.strike"),
            expiration=date.fromisoformat(str(contract_payload.get("expiration"))),
            bid=_required_float(contract_payload.get("bid"), "contract.bid"),
            ask=_required_float(contract_payload.get("ask"), "contract.ask"),
            delta=_optional_float(contract_payload.get("delta")),
            implied_volatility=_optional_float(contract_payload.get("implied_volatility")),
            volume=_optional_int(contract_payload.get("volume")),
            open_interest=_optional_int(contract_payload.get("open_interest")),
        ),
    )


def _sell_put_scan_from_payload(payload: dict[str, object]):
    account_payload = payload.get("account") if isinstance(payload.get("account"), dict) else {}
    config_payload = payload.get("config") if isinstance(payload.get("config"), dict) else {}
    if not isinstance(account_payload, dict) or not isinstance(config_payload, dict):
        raise ValueError("account and config must be objects")

    symbol = str(payload.get("symbol") or "").upper()
    if not symbol:
        raise ValueError("symbol is required")
    as_of = date.fromisoformat(str(payload.get("as_of") or date.today().isoformat()))

    config = SellPutScanConfig(
        min_dte=int(config_payload.get("min_dte") or 14),
        max_dte=int(config_payload.get("max_dte") or 45),
        min_otm_pct=_float(config_payload.get("min_otm_pct"), 0.05),
        max_otm_pct=_float(config_payload.get("max_otm_pct"), 0.30),
        max_cash_per_trade_pct=_float(config_payload.get("max_cash_per_trade_pct"), 0.4),
        max_candidates_per_symbol=int(config_payload.get("max_candidates_per_symbol") or 12),
    )
    account = AccountProfile(
        equity=_float(account_payload.get("equity"), 5_000),
        cash=_float(account_payload.get("cash"), 5_000),
        max_cash_per_trade_pct=config.max_cash_per_trade_pct,
    )
    client = LongbridgeCLIClient.from_data_config(SETTINGS.data)
    quote = client.fetch_quote_snapshot(symbol)
    underlying_price = _required_float(
        payload.get("underlying_price") or quote.get("current_price") or quote.get("regular_market_price"),
        "underlying_price",
    )
    expirations = [
        expiration
        for expiration in client.fetch_option_expirations(symbol)
        if config.min_dte <= (expiration - as_of).days <= config.max_dte
    ]
    chains = {expiration: client.fetch_option_chain(symbol, expiration) for expiration in expirations}
    option_volume = _safe_option_volume(client, symbol)
    return OPTIONS_SERVICE.scan_sell_put(
        symbol=symbol,
        underlying_price=underlying_price,
        as_of=as_of,
        account=account,
        expirations=expirations,
        chains_by_expiration=chains,
        option_volume_payload=option_volume,
        config=config,
    )


def _safe_option_volume(client: LongbridgeCLIClient, symbol: str) -> dict[str, object] | None:
    try:
        return client.fetch_option_volume(symbol)
    except Exception:  # noqa: BLE001 - option volume is useful context, not required for the scan.
        return None


def _required_float(value: object, field_name: str) -> float:
    result = _optional_float(value)
    if result is None:
        raise ValueError(f"{field_name} is required")
    return result


def _float(value: object, default: float) -> float:
    result = _optional_float(value)
    return default if result is None else result


def _bool(value: object, default: bool) -> bool:
    if value in (None, ""):
        return default
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"invalid boolean value: {value}")


def _optional_float(value: object) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def _optional_int(value: object) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def _optional_str(value: object) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


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
