"""Local JSONL operation logging for data updates and provider calls."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from typing import Any

from quant_platform.config import Settings
from quant_platform.time_utils import now_beijing


class OperationLogger:
    def __init__(self, root: Path, namespace: str) -> None:
        self.root = root
        self.namespace = namespace
        self.log_to_console = _env_bool("QP_LOG_TO_CONSOLE")

    def info(self, action: str, **fields: Any) -> None:
        self._write("info", action, fields)

    def error(self, action: str, **fields: Any) -> None:
        self._write("error", action, fields)

    def _write(self, level: str, action: str, fields: dict[str, Any]) -> None:
        now = now_beijing()
        path = self.root / f"{self.namespace}_{now.strftime('%Y%m%d')}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "timestamp": now.isoformat(),
            "timezone": "Asia/Shanghai",
            "level": level,
            "action": action,
            **_sanitize(fields),
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
        if self.log_to_console:
            print(_format_console_line(self.namespace, payload), file=sys.stderr)


def operation_log_root(settings: Settings) -> Path:
    return settings.storage.processed_dir.parent / "logs"


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: ("***" if "key" in key.lower() or "token" in key.lower() else _sanitize(item)) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    return value


def _format_console_line(namespace: str, payload: dict[str, Any]) -> str:
    timestamp = str(payload.get("timestamp") or "")
    level = str(payload.get("level") or "info").upper()
    action = str(payload.get("action") or "")
    fields = [
        f"{key}={_short_value(value)}"
        for key, value in payload.items()
        if key not in {"timestamp", "timezone", "level", "action"}
    ][:8]
    suffix = f" {' '.join(fields)}" if fields else ""
    return f"[{timestamp}] {level} {namespace}.{action}{suffix}"


def _short_value(value: Any, *, limit: int = 160) -> str:
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False, default=str)
    else:
        text = str(value)
    if len(text) > limit:
        return text[: limit - 3] + "..."
    return text


def _env_bool(key: str) -> bool:
    return os.environ.get(key, "").strip().lower() in {"1", "true", "yes", "on"}
