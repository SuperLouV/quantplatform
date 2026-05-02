"""Configuration loading helpers."""

from __future__ import annotations

from ast import literal_eval
from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class AppConfig:
    name: str
    env: str


@dataclass(slots=True)
class DataConfig:
    provider: str
    timezone: str
    quote_provider: str = "auto"
    fred_api_key: str = ""
    user_agent: str = "quant-platform/0.1"
    request_min_interval_seconds: float = 0.5
    request_max_retries: int = 2
    request_backoff_seconds: float = 1.0
    request_timeout_seconds: float = 15.0
    yfinance_history_repair: bool = True
    yfinance_history_prepost: bool = False
    yfinance_initial_history_years: int = 10
    longbridge_cli_binary: str = "longbridge"


@dataclass(slots=True)
class StorageConfig:
    raw_dir: Path
    processed_dir: Path
    reference_dir: Path
    cache_dir: Path
    state_db: Path
    raw_format: str = "json"
    processed_format: str = "parquet"


@dataclass(slots=True)
class SchedulerConfig:
    enabled: bool = True
    daily_refresh_time_beijing: str = "06:30"
    daily_refresh_pool: str = "data/reference/system/stock_pools/preset/default_core.json"
    daily_refresh_workers: int = 8
    daily_refresh_update_events: bool = True
    poll_interval_seconds: int = 60


@dataclass(slots=True)
class Settings:
    app: AppConfig
    data: DataConfig
    storage: StorageConfig
    scheduler: SchedulerConfig


def load_mapping_file(path: str | Path) -> dict[str, Any]:
    return _read_yaml(Path(path))


def _read_yaml(path: Path) -> dict[str, Any]:
    data = _parse_simple_yaml(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Config file must contain a mapping: {path}")
    return data


def _parse_simple_yaml(text: str) -> dict[str, Any]:
    """Parse a small YAML subset used by project config templates.

    Supported:
    - nested mappings by indentation
    - string, int, float, bool, and empty-string scalars
    - blank lines and whole-line comments
    """

    root: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any]]] = [(-1, root)]

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue

        indent = len(raw_line) - len(raw_line.lstrip(" "))
        stripped = raw_line.strip()
        if ":" not in stripped:
            raise ValueError(f"Unsupported config line: {raw_line}")

        key, raw_value = stripped.split(":", 1)
        key = key.strip()
        value = raw_value.strip()

        while len(stack) > 1 and indent <= stack[-1][0]:
            stack.pop()

        current = stack[-1][1]
        if not value:
            nested: dict[str, Any] = {}
            current[key] = nested
            stack.append((indent, nested))
            continue

        current[key] = _parse_scalar(value)

    return root


def _parse_scalar(value: str) -> Any:
    if value in {"true", "True"}:
        return True
    if value in {"false", "False"}:
        return False
    if value in {'""', "''"}:
        return ""

    try:
        return literal_eval(value)
    except (SyntaxError, ValueError):
        return value


def load_settings(path: str | Path) -> Settings:
    config_path = Path(path)
    _load_local_env(config_path.parent.parent / ".env")
    data = load_mapping_file(config_path)

    app = data.get("app", {})
    market_data = data.get("data", {})
    storage = data.get("storage", {})
    scheduler = data.get("scheduler", {})
    base_dir = config_path.parent.parent

    return Settings(
        app=AppConfig(
            name=app.get("name", "quant-platform"),
            env=app.get("env", "dev"),
        ),
        data=DataConfig(
            provider=market_data.get("provider", "yfinance"),
            quote_provider=market_data.get("quote_provider", "auto"),
            timezone=market_data.get("timezone", "America/New_York"),
            fred_api_key=os.environ.get("FRED_API_KEY") or market_data.get("fred_api_key", ""),
            user_agent=market_data.get("user_agent", "quant-platform/0.1"),
            request_min_interval_seconds=float(market_data.get("request_min_interval_seconds", 0.5)),
            request_max_retries=int(market_data.get("request_max_retries", 2)),
            request_backoff_seconds=float(market_data.get("request_backoff_seconds", 1.0)),
            request_timeout_seconds=float(market_data.get("request_timeout_seconds", 15.0)),
            yfinance_history_repair=bool(market_data.get("yfinance_history_repair", True)),
            yfinance_history_prepost=bool(market_data.get("yfinance_history_prepost", False)),
            yfinance_initial_history_years=int(
                os.environ.get("QP_YFINANCE_INITIAL_HISTORY_YEARS")
                or market_data.get("yfinance_initial_history_years", 10)
            ),
            longbridge_cli_binary=os.environ.get("QP_LONGBRIDGE_CLI_BINARY")
            or market_data.get("longbridge_cli_binary", "longbridge"),
        ),
        storage=StorageConfig(
            raw_dir=(base_dir / storage.get("raw_dir", "data/raw")).resolve(),
            processed_dir=(base_dir / storage.get("processed_dir", "data/processed")).resolve(),
            reference_dir=(base_dir / storage.get("reference_dir", "data/reference")).resolve(),
            cache_dir=(base_dir / storage.get("cache_dir", "data/cache")).resolve(),
            state_db=(base_dir / storage.get("state_db", "data/system/state.db")).resolve(),
            raw_format=storage.get("raw_format", "json"),
            processed_format=storage.get("processed_format", "parquet"),
        ),
        scheduler=SchedulerConfig(
            enabled=_env_bool("QP_SCHEDULER_ENABLED", bool(scheduler.get("enabled", True))),
            daily_refresh_time_beijing=os.environ.get("QP_DAILY_REFRESH_TIME_BEIJING")
            or scheduler.get("daily_refresh_time_beijing", "06:30"),
            daily_refresh_pool=os.environ.get("QP_DAILY_REFRESH_POOL")
            or scheduler.get("daily_refresh_pool", "data/reference/system/stock_pools/preset/default_core.json"),
            daily_refresh_workers=int(
                os.environ.get("QP_DAILY_REFRESH_WORKERS")
                or scheduler.get("daily_refresh_workers", 8)
            ),
            daily_refresh_update_events=_env_bool(
                "QP_DAILY_REFRESH_UPDATE_EVENTS",
                bool(scheduler.get("daily_refresh_update_events", True)),
            ),
            poll_interval_seconds=int(
                os.environ.get("QP_SCHEDULER_POLL_INTERVAL_SECONDS")
                or scheduler.get("poll_interval_seconds", 60)
            ),
        ),
    )


def _load_local_env(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        os.environ[key] = value.strip().strip('"').strip("'")


def _env_bool(key: str, default: bool) -> bool:
    value = os.environ.get(key)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}
