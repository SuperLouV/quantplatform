"""Local JSONL operation logging for data updates and provider calls."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class OperationLogger:
    def __init__(self, root: Path, namespace: str) -> None:
        self.root = root
        self.namespace = namespace

    def info(self, action: str, **fields: Any) -> None:
        self._write("info", action, fields)

    def error(self, action: str, **fields: Any) -> None:
        self._write("error", action, fields)

    def _write(self, level: str, action: str, fields: dict[str, Any]) -> None:
        now = datetime.now(tz=UTC)
        path = self.root / f"{self.namespace}_{now.strftime('%Y%m%d')}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "timestamp": now.isoformat(),
            "level": level,
            "action": action,
            **_sanitize(fields),
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: ("***" if "key" in key.lower() or "token" in key.lower() else _sanitize(item)) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    return value
