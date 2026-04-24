"""Filesystem layout helpers for raw, processed, reference, and cache data."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from quant_platform.config import StorageConfig


@dataclass(slots=True)
class DataLayout:
    storage: StorageConfig

    def ensure(self) -> None:
        for path in (
            self.storage.raw_dir,
            self.storage.processed_dir,
            self.storage.reference_dir,
            self.storage.cache_dir,
            self.storage.state_db.parent,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def raw_symbol_path(self, provider: str, dataset: str, symbol: str, partition: str) -> Path:
        return (
            self.storage.raw_dir
            / provider
            / dataset
            / partition
            / f"{symbol}.{self.storage.raw_format}"
        )

    def processed_dataset_path(self, dataset: str, partition: str) -> Path:
        return self.storage.processed_dir / dataset / f"{partition}.{self.storage.processed_format}"

    def processed_symbol_path(self, provider: str, dataset: str, symbol: str) -> Path:
        return (
            self.storage.processed_dir
            / provider
            / dataset
            / f"{symbol}.{self.storage.processed_format}"
        )

    def reference_path(self, provider: str, dataset: str) -> Path:
        return self.storage.reference_dir / provider / f"{dataset}.{self.storage.processed_format}"

    def reference_file_path(self, provider: str, dataset: str, extension: str) -> Path:
        return self.storage.reference_dir / provider / f"{dataset}.{extension}"

    def cache_path(self, provider: str, name: str, extension: str = "json") -> Path:
        return self.storage.cache_dir / provider / f"{name}.{extension}"

    def stock_pool_path(self, pool_type: str, pool_id: str, extension: str = "json") -> Path:
        return self.storage.reference_dir / "system" / "stock_pools" / pool_type / f"{pool_id}.{extension}"

    def stock_snapshot_path(self, symbol: str, extension: str | None = None) -> Path:
        ext = extension or self.storage.processed_format
        return self.storage.processed_dir / "snapshots" / f"{symbol}.{ext}"

    def ai_analysis_path(self, target_type: str, target_id: str, extension: str = "json") -> Path:
        return Path("outputs") / "reports" / "ai_analysis" / target_type / f"{target_id}.{extension}"
