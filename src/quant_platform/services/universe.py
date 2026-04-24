"""Compatibility wrapper around the new stock pool service."""

from __future__ import annotations

from pathlib import Path

from quant_platform.config import Settings
from quant_platform.core.product_models import StockPoolSnapshot
from quant_platform.screeners import UniverseConfig
from quant_platform.services.stock_pool import StockPoolService


class UniverseService:
    def __init__(self, settings: Settings) -> None:
        self.stock_pool_service = StockPoolService(settings)

    def build_from_config(self, config: UniverseConfig) -> list[StockPoolSnapshot]:
        return self.stock_pool_service.build_from_config(config)

    def write_snapshot(self, result: list[StockPoolSnapshot]) -> Path:
        paths = self.stock_pool_service.write_snapshots(result)
        return paths[0]
