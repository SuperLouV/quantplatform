"""Helpers for keeping command output readable."""

from __future__ import annotations

import contextlib
import os
import sys
import tempfile
from collections.abc import Iterator


@contextlib.contextmanager
def quiet_known_native_stderr() -> Iterator[None]:
    """Filter known native-library stderr noise while preserving real errors."""
    if _env_bool("QP_LOG_TO_CONSOLE"):
        yield
        return

    original_fd = os.dup(2)
    with tempfile.TemporaryFile(mode="w+b") as captured:
        os.dup2(captured.fileno(), 2)
        try:
            yield
        finally:
            os.dup2(original_fd, 2)
            os.close(original_fd)
            captured.seek(0)
            lines = captured.read().decode("utf-8", errors="replace").splitlines()

    for line in lines:
        if not _is_known_native_noise(line):
            print(line, file=sys.stderr)


def _is_known_native_noise(line: str) -> bool:
    if "arrow/util/cpu_info.cc" in line and "sysctlbyname failed" in line:
        return True
    return "HTTP Error 404:" in line and "No fundamentals data found for symbol" in line


def _env_bool(name: str) -> bool:
    value = os.environ.get(name, "")
    return value.strip().lower() in {"1", "true", "yes", "on"}
