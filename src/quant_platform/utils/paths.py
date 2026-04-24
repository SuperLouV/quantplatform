"""Filesystem helpers for local project storage."""

from __future__ import annotations

from pathlib import Path

from quant_platform.config import StorageConfig


def ensure_storage_dirs(storage: StorageConfig) -> list[Path]:
    created: list[Path] = []
    for path in (
        storage.raw_dir,
        storage.processed_dir,
        storage.reference_dir,
        storage.cache_dir,
        storage.state_db.parent,
    ):
        path.mkdir(parents=True, exist_ok=True)
        created.append(path)
    return created
