"""Batch snapshot update service for stock pools."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from quant_platform.clients.yfinance import YFinanceClient
from quant_platform.config import Settings
from quant_platform.core.product_models import StockPoolSnapshot, StockSnapshot
from quant_platform.indicators import IndicatorEngine
from quant_platform.services.ai_analysis import AIAnalysisService
from quant_platform.services.bootstrap import bootstrap_local_state
from quant_platform.services.data_quality import DataQualityReport, summarize_quality, validate_quote_snapshot
from quant_platform.services.operation_log import OperationLogger, operation_log_root
from quant_platform.services.stock_snapshot import StockSnapshotService
from quant_platform.time_utils import iso_beijing, now_beijing


class StockSnapshotBatchService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.artifacts = bootstrap_local_state(settings)
        self.client = YFinanceClient.from_data_config(settings.data)
        self.snapshot_service = StockSnapshotService()
        self.ai_service = AIAnalysisService()
        self.indicator_engine = IndicatorEngine()
        self.logger = OperationLogger(operation_log_root(settings), "stock_snapshots")

    def load_pool(self, path: str | Path) -> StockPoolSnapshot:
        pool_path = Path(path)
        payload = json.loads(pool_path.read_text(encoding="utf-8"))
        members = payload.get("members", [])
        pool = StockPoolSnapshot(
            pool_id=payload["pool_id"],
            name=payload["name"],
            pool_type=payload["pool_type"],
            source=payload["source"],
            market=payload["market"],
            symbols=payload["symbols"],
            members=[],
            updated_at=datetime.fromisoformat(payload["updated_at"]),
            notes=payload.get("notes"),
        )
        self.logger.info("stock_pool.load.success", pool_id=pool.pool_id, symbols=len(pool.symbols), path=str(pool_path))
        return pool

    def update_pool(self, pool: StockPoolSnapshot, *, max_workers: int = 8) -> tuple[list[Path], Path]:
        self.logger.info("stock_snapshots.pool_update.start", pool_id=pool.pool_id, symbols=len(pool.symbols), workers=max_workers)
        snapshot_paths: list[Path] = []
        dashboard_entries: list[dict[str, object]] = []
        quality_reports: list[DataQualityReport] = []

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(self.client.fetch_quote_snapshot, symbol): symbol
                for symbol in pool.symbols
            }
            for future in as_completed(futures):
                symbol = futures[future]
                try:
                    self.logger.info("stock_snapshots.symbol.result.start", pool_id=pool.pool_id, symbol=symbol)
                    quote = future.result()
                    quality = validate_quote_snapshot(symbol, quote)
                    quality_reports.append(quality)
                    snapshot = self.create_snapshot_from_quote(
                        symbol,
                        pool_ids=[pool.pool_id],
                        quote=quote,
                        quality=quality,
                    )
                    self.attach_local_indicators(snapshot)
                    self.logger.info(
                        "stock_snapshots.symbol.success",
                        pool_id=pool.pool_id,
                        symbol=symbol,
                        quality=quality.status,
                        status=snapshot.screening_status,
                        latest_close=snapshot.latest_close,
                    )
                except Exception as exc:
                    quality_reports.append(
                        DataQualityReport(
                            symbol=symbol,
                            status="error",
                            issues=[],
                        )
                    )
                    snapshot = StockSnapshot(
                        symbol=symbol,
                        pool_ids=[pool.pool_id],
                        screening_status="error",
                        screening_reasons=[str(exc)],
                        as_of=now_beijing(),
                    )
                    self.logger.error("stock_snapshots.symbol.error", pool_id=pool.pool_id, symbol=symbol, error=str(exc))

                path = self.write_snapshot(snapshot)
                snapshot_paths.append(path)
                dashboard_entries.append(self.serialize_snapshot(snapshot))

        dashboard_path = self.write_dashboard(pool, dashboard_entries, quality_reports=quality_reports)
        self.logger.info(
            "stock_snapshots.pool_update.success",
            pool_id=pool.pool_id,
            snapshots=len(snapshot_paths),
            dashboard_path=str(dashboard_path),
            quality=summarize_quality(quality_reports),
        )
        return snapshot_paths, dashboard_path

    def write_snapshot(self, snapshot: StockSnapshot) -> Path:
        path = self.artifacts.layout.stock_snapshot_path(snapshot.symbol, "json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(_serialize_snapshot(snapshot), ensure_ascii=False, indent=2), encoding="utf-8")
        self.logger.info(
            "stock_snapshots.write_snapshot.success",
            symbol=snapshot.symbol,
            path=str(path),
            status=snapshot.screening_status,
            as_of=snapshot.as_of.isoformat() if snapshot.as_of else None,
        )
        return path

    def write_dashboard(
        self,
        pool: StockPoolSnapshot,
        snapshots: list[dict[str, object]],
        *,
        quality_reports: list[DataQualityReport],
    ) -> Path:
        path = self.artifacts.layout.reference_file_path("system", "dashboard_data", "json")
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "generated_at": iso_beijing(),
            "timezone": "Asia/Shanghai",
            "pool": {
                "pool_id": pool.pool_id,
                "name": pool.name,
                "pool_type": pool.pool_type,
                "source": pool.source,
                "symbol_count": len(pool.symbols),
            },
            "data_quality": summarize_quality(quality_reports),
            "snapshot_status": _summarize_snapshot_status(snapshots),
            "snapshots": snapshots,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        self.logger.info(
            "stock_snapshots.write_dashboard.success",
            pool_id=pool.pool_id,
            path=str(path),
            snapshots=len(snapshots),
            data_quality=payload["data_quality"],
            snapshot_status=payload["snapshot_status"],
        )
        return path

    def create_snapshot_from_quote(
        self,
        symbol: str,
        *,
        pool_ids: list[str],
        quote: dict[str, object],
        quality: DataQualityReport | None = None,
    ) -> StockSnapshot:
        quality = quality or validate_quote_snapshot(symbol, quote)
        screening_status = "ready"
        if quality.status == "warning":
            screening_status = "data_warning"
        if quality.status == "error":
            screening_status = "data_error"

        return StockSnapshot(
            symbol=symbol,
            pool_ids=pool_ids,
            company_name=quote.get("company_name"),
            sector=quote.get("sector"),
            industry=quote.get("industry"),
            currency=quote.get("currency"),
            open_price=quote.get("open_price"),
            high_price=quote.get("high_price"),
            low_price=quote.get("low_price"),
            latest_close=quote.get("latest_close"),
            current_price=quote.get("current_price"),
            regular_market_price=quote.get("regular_market_price"),
            pre_market_price=quote.get("pre_market_price"),
            post_market_price=quote.get("post_market_price"),
            market_state=quote.get("market_state"),
            latest_history_date_us=quote.get("latest_history_date_us"),
            snapshot_refreshed_at_beijing=quote.get("snapshot_refreshed_at_beijing"),
            market_timezone=quote.get("market_timezone"),
            previous_close=quote.get("previous_close"),
            change_percent=quote.get("change_percent"),
            latest_volume=quote.get("latest_volume"),
            market_cap=quote.get("market_cap"),
            avg_dollar_volume=quote.get("avg_dollar_volume"),
            trailing_pe=quote.get("trailing_pe"),
            forward_pe=quote.get("forward_pe"),
            next_earnings_date=quote.get("next_earnings_date"),
            exchange=quote.get("exchange"),
            screening_status=screening_status,
            screening_reasons=quality.messages,
            as_of=now_beijing(),
        )

    def attach_local_indicators(self, snapshot: StockSnapshot, *, max_staleness_days: int = 7) -> None:
        path = self.artifacts.layout.processed_symbol_path(self.client.provider_name, "bars", snapshot.symbol)
        if not path.exists():
            snapshot.screening_reasons.append("warning:missing_bars:本地历史日线不存在，未计算技术指标。")
            _mark_data_warning(snapshot)
            self.logger.info("stock_snapshots.indicators.skipped", symbol=snapshot.symbol, reason="missing_bars", path=str(path))
            return

        try:
            computation = self.indicator_engine.compute_from_parquet(path)
        except Exception as exc:  # noqa: BLE001 - indicator input quality can vary by provider.
            snapshot.screening_reasons.append(f"warning:indicator_error:技术指标计算失败：{exc}")
            _mark_data_warning(snapshot)
            self.logger.error("stock_snapshots.indicators.error", symbol=snapshot.symbol, path=str(path), error=str(exc))
            return

        if computation.series.empty or "timestamp" not in computation.series.columns:
            snapshot.screening_reasons.append("warning:empty_bars:本地历史日线为空，未计算技术指标。")
            _mark_data_warning(snapshot)
            self.logger.info("stock_snapshots.indicators.skipped", symbol=snapshot.symbol, reason="empty_bars", path=str(path))
            return

        latest_timestamp = pd.Timestamp(computation.series.iloc[-1]["timestamp"])
        if latest_timestamp.tzinfo is None:
            latest_timestamp = latest_timestamp.tz_localize(UTC)
        else:
            latest_timestamp = latest_timestamp.tz_convert(UTC)

        reference_time = snapshot.as_of or now_beijing()
        age_days = (reference_time.date() - latest_timestamp.date()).days
        if age_days < 0:
            snapshot.screening_reasons.append(
                f"warning:future_bars:本地历史日线最新日期为 {latest_timestamp.date().isoformat()}，"
                f"晚于快照时间 {reference_time.date().isoformat()}，未写入技术指标。"
            )
            _mark_data_warning(snapshot)
            self.logger.info(
                "stock_snapshots.indicators.skipped",
                symbol=snapshot.symbol,
                reason="future_bars",
                bars_as_of=latest_timestamp.isoformat(),
                reference_time=reference_time.isoformat(),
            )
            return
        if age_days > max_staleness_days:
            snapshot.screening_reasons.append(
                f"warning:stale_bars:本地历史日线最新日期为 {latest_timestamp.date().isoformat()}，"
                f"距离快照时间 {reference_time.date().isoformat()} 超过 {max_staleness_days} 天，未写入技术指标。"
            )
            _mark_data_warning(snapshot)
            self.logger.info(
                "stock_snapshots.indicators.skipped",
                symbol=snapshot.symbol,
                reason="stale_bars",
                age_days=age_days,
                max_staleness_days=max_staleness_days,
                bars_as_of=latest_timestamp.isoformat(),
                reference_time=reference_time.isoformat(),
            )
            return

        snapshot.indicators = {
            **computation.latest,
            "indicators_as_of": latest_timestamp.isoformat(),
            "indicators_provider": self.client.provider_name,
        }
        self.logger.info(
            "stock_snapshots.indicators.success",
            symbol=snapshot.symbol,
            path=str(path),
            indicators_as_of=latest_timestamp.isoformat(),
            columns=len(computation.latest),
        )

    def serialize_snapshot(self, snapshot: StockSnapshot) -> dict[str, object]:
        return _serialize_snapshot(snapshot)


def _serialize_snapshot(snapshot: StockSnapshot) -> dict[str, object]:
    payload = asdict(snapshot)
    if snapshot.as_of is not None:
        payload["as_of"] = snapshot.as_of.isoformat()
    return payload


def _mark_data_warning(snapshot: StockSnapshot) -> None:
    if snapshot.screening_status == "ready":
        snapshot.screening_status = "data_warning"


def _summarize_snapshot_status(snapshots: list[dict[str, object]]) -> dict[str, int]:
    summary: dict[str, int] = {}
    for snapshot in snapshots:
        status = str(snapshot.get("screening_status") or "unknown")
        summary[status] = summary.get(status, 0) + 1
    return summary
