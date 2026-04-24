"""Lightweight provider request protection utilities."""

from __future__ import annotations

import threading
import time
from random import random
from dataclasses import dataclass
from typing import Callable, TypeVar


T = TypeVar("T")


class ProviderRequestError(RuntimeError):
    """Raised when a protected provider request fails after retries."""


@dataclass(slots=True)
class ProviderRequestPolicy:
    min_interval_seconds: float = 0.5
    max_retries: int = 2
    backoff_seconds: float = 1.0
    timeout_seconds: float = 15.0


class ProviderRequestGuard:
    """Apply simple rate limiting and retry/backoff around provider calls."""

    def __init__(self, policy: ProviderRequestPolicy | None = None) -> None:
        self.policy = policy or ProviderRequestPolicy()
        self._lock = threading.Lock()
        self._last_started_at = 0.0

    def call(self, operation: str, func: Callable[[], T]) -> T:
        attempts = max(1, self.policy.max_retries + 1)
        last_error: Exception | None = None

        for attempt in range(1, attempts + 1):
            self._wait_for_slot()
            try:
                return func()
            except Exception as exc:  # noqa: BLE001 - provider errors are not stable.
                last_error = exc
                if attempt >= attempts:
                    break
                jitter = 1 + random() * 0.5
                time.sleep(self.policy.backoff_seconds * attempt * jitter)

        raise ProviderRequestError(
            f"{operation} failed after {attempts} attempt(s): {last_error}"
        ) from last_error

    def _wait_for_slot(self) -> None:
        with self._lock:
            now = time.monotonic()
            wait_seconds = self.policy.min_interval_seconds - (now - self._last_started_at)
            if wait_seconds > 0:
                time.sleep(wait_seconds)
            self._last_started_at = time.monotonic()
