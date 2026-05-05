"""End-of-day refresh pipeline for next-session preparation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from quant_platform.config import Settings
from quant_platform.services.bootstrap import bootstrap_local_state
from quant_platform.services.market_events import MarketEventService
from quant_platform.services.operation_log import OperationLogger, operation_log_root
from quant_platform.services.stock_snapshot_batch import StockSnapshotBatchService
from quant_platform.services.yfinance_history import YFinanceHistoryUpdater
from quant_platform.time_utils import iso_beijing, latest_completed_us_market_date, now_beijing


@dataclass(slots=True)
class DailyRefreshResult:
    pool_id: str
    market_date_us: date
    generated_at_beijing: str
    summary_path: Path
    dashboard_path: Path
    snapshot_count: int
    history: dict[str, dict[str, Any]]
    market_events_count: int | None = None
    supplemental_outputs: dict[str, dict[str, Any]] | None = None


class DailyRefreshService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.artifacts = bootstrap_local_state(settings)
        self.snapshot_batch = StockSnapshotBatchService(settings)
        self.history_updater = YFinanceHistoryUpdater(settings)
        self.market_events = MarketEventService(settings)
        self.logger = OperationLogger(operation_log_root(settings), "daily_refresh")

    def run(
        self,
        *,
        pool_path: str | Path,
        market_date_us: date | None = None,
        workers: int = 8,
        update_events: bool = True,
    ) -> DailyRefreshResult:
        market_date = market_date_us or latest_completed_us_market_date(now_beijing())
        supplemental_outputs: dict[str, dict[str, Any]] = {}
        if self.settings.scheduler.daily_refresh_sync_longbridge_pool:
            self.logger.notice("daily_refresh.longbridge_pool_sync.start")
            sync_result = self._sync_longbridge_pool()
            supplemental_outputs["longbridge_pool_sync"] = sync_result

        pool = self.snapshot_batch.load_pool(pool_path)
        self.logger.notice(
            "daily_refresh.start",
            pool_id=pool.pool_id,
            symbols=len(pool.symbols),
            market_date_us=market_date.isoformat(),
        )
        self.logger.info(
            "daily_refresh.start",
            pool_id=pool.pool_id,
            symbols=len(pool.symbols),
            market_date_us=market_date.isoformat(),
            workers=workers,
            update_events=update_events,
        )

        history_results: dict[str, dict[str, Any]] = {}
        for symbol in pool.symbols:
            try:
                result = self.history_updater.update_symbol(symbol, end=market_date + timedelta(days=1))
                status = _history_status(result.cursor, market_date)
                history_results[symbol] = {
                    "status": status,
                    "rows_fetched": result.rows_written,
                    "rows_written": result.rows_written,
                    "total_rows": result.total_rows,
                    "earliest_date": result.earliest_date,
                    "latest_date": result.latest_date,
                    "cursor": result.cursor,
                    "start_reason": result.start_reason,
                    "requested_start": result.requested_start,
                    "raw_path": str(result.raw_path),
                    "processed_path": str(result.processed_path),
                }
                if status != "success":
                    history_results[symbol]["reason"] = "cursor_before_market_date"
                    self.logger.error(
                        "daily_refresh.history.empty",
                        pool_id=pool.pool_id,
                        symbol=symbol,
                        rows_written=result.rows_written,
                        cursor=result.cursor,
                        market_date_us=market_date.isoformat(),
                    )
            except Exception as exc:  # noqa: BLE001 - keep the daily refresh moving across symbols.
                history_results[symbol] = {"status": "error", "error": str(exc)}
                self.logger.error("daily_refresh.history.error", pool_id=pool.pool_id, symbol=symbol, error=str(exc))

        self.logger.notice(
            "daily_refresh.history.done",
            success=_count_history_status(history_results, "success"),
            empty=_count_history_status(history_results, "empty"),
            error=_count_history_status(history_results, "error"),
        )
        snapshot_paths, dashboard_path = self.snapshot_batch.update_pool(pool, max_workers=workers)
        self.logger.notice("daily_refresh.snapshots.done", snapshots=len(snapshot_paths), dashboard_path=str(dashboard_path))

        market_events_count: int | None = None
        if update_events:
            try:
                events = self.market_events.update_events()
                market_events_count = len(events.events)
                self.logger.notice("daily_refresh.market_events.done", events=market_events_count)
            except Exception as exc:  # noqa: BLE001 - event failures should be visible but not block quote refresh.
                self.logger.error("daily_refresh.market_events.error", pool_id=pool.pool_id, error=str(exc))
                self.logger.notice("daily_refresh.market_events.error", error=str(exc))

        result = DailyRefreshResult(
            pool_id=pool.pool_id,
            market_date_us=market_date,
            generated_at_beijing=iso_beijing(),
            summary_path=self._summary_path(pool.pool_id, market_date),
            dashboard_path=dashboard_path,
            snapshot_count=len(snapshot_paths),
            history=history_results,
            market_events_count=market_events_count,
            supplemental_outputs=supplemental_outputs,
        )
        self._write_summary(result)
        supplemental_outputs.update(self._generate_pre_report_outputs(pool_id=pool.pool_id, market_date=market_date))
        result.supplemental_outputs = supplemental_outputs
        self._write_summary(result)
        if self.settings.scheduler.daily_refresh_generate_daily_report:
            supplemental_outputs["daily_report"] = self._run_daily_report(pool_id=pool.pool_id, market_date=market_date)
            result.supplemental_outputs = supplemental_outputs
            self._write_summary(result)
        self.logger.info(
            "daily_refresh.success",
            pool_id=pool.pool_id,
            market_date_us=market_date.isoformat(),
            summary_path=str(result.summary_path),
            dashboard_path=str(dashboard_path),
            snapshot_count=len(snapshot_paths),
            history_success=_count_history_status(history_results, "success"),
            history_empty=_count_history_status(history_results, "empty"),
            history_error=_count_history_status(history_results, "error"),
            market_events_count=market_events_count,
        )
        self.logger.notice(
            "daily_refresh.success",
            pool_id=pool.pool_id,
            market_date_us=market_date.isoformat(),
            supplemental=_summarize_supplemental(supplemental_outputs),
            summary_path=str(result.summary_path),
        )
        return result

    def _sync_longbridge_pool(self) -> dict[str, Any]:
        try:
            from quant_platform.services.longbridge_pools import LongbridgeStockPoolService

            sync = LongbridgeStockPoolService(self.settings).sync()
            payload = {
                "status": "success",
                "generated_at_beijing": sync.generated_at_beijing,
                "positions": sync.position_count,
                "watchlist": sync.watchlist_count,
                "combined": sync.combined_count,
                "excluded": sync.excluded_count,
                "core_pool_path": str(sync.pool_paths.get("longbridge_core")),
                "metadata_path": str(sync.metadata_path),
            }
            self.logger.info("daily_refresh.longbridge_pool_sync.success", **payload)
            self.logger.notice(
                "daily_refresh.longbridge_pool_sync.success",
                positions=sync.position_count,
                watchlist=sync.watchlist_count,
                combined=sync.combined_count,
                excluded=sync.excluded_count,
            )
            return payload
        except Exception as exc:  # noqa: BLE001 - stale local pool is still usable if sync fails.
            self.logger.error("daily_refresh.longbridge_pool_sync.error", error=str(exc))
            self.logger.notice("daily_refresh.longbridge_pool_sync.error", error=str(exc))
            return {"status": "error", "error": str(exc)}

    def _generate_pre_report_outputs(self, *, pool_id: str, market_date: date) -> dict[str, dict[str, Any]]:
        outputs: dict[str, dict[str, Any]] = {}
        if self.settings.scheduler.daily_refresh_generate_account_health:
            self.logger.notice("daily_refresh.account_health.start")
            outputs["account_health"] = self._run_account_health()
        if self.settings.scheduler.daily_refresh_generate_options_advice:
            self.logger.notice("daily_refresh.options_advice.start")
            outputs["options_advice"] = self._run_options_advice()
        if self.settings.scheduler.daily_refresh_generate_macro_risk:
            self.logger.notice("daily_refresh.macro_risk.start")
            outputs["macro_risk"] = self._run_macro_risk(pool_id=pool_id, market_date=market_date)
        if self.settings.scheduler.daily_refresh_generate_ai_analysis:
            self.logger.notice("daily_refresh.ai_dashboard.start")
            outputs["ai_dashboard"] = self._run_ai_dashboard(pool_id=pool_id)
            self.logger.notice("daily_refresh.ai_account_health.start")
            outputs["ai_account_health"] = self._run_ai_account_health()
            if self.settings.scheduler.daily_refresh_generate_options_advice:
                self.logger.notice("daily_refresh.ai_options_advice.start")
                outputs["ai_options_advice"] = self._run_ai_options_advice()
        return outputs

    def _run_account_health(self) -> dict[str, Any]:
        try:
            from quant_platform.services.portfolio_health import AccountHealthService

            result = AccountHealthService(self.settings).generate(as_of=now_beijing().date())
            payload = {
                "status": "success",
                "generated_at_beijing": result.generated_at_beijing,
                "position_count": result.position_count,
                "health_score": result.health_score,
                "health_state": result.health_state,
                "warning_count": result.warning_count,
                "json_path": str(result.json_path),
                "markdown_path": str(result.markdown_path),
            }
            self.logger.info("daily_refresh.account_health.success", **payload)
            self.logger.notice(
                "daily_refresh.account_health.success",
                positions=result.position_count,
                score=result.health_score,
                state=result.health_state,
                warnings=result.warning_count,
            )
            return payload
        except Exception as exc:  # noqa: BLE001 - account report must not break market data refresh.
            self.logger.error("daily_refresh.account_health.error", error=str(exc))
            self.logger.notice("daily_refresh.account_health.error", error=str(exc))
            return {"status": "error", "error": str(exc)}

    def _run_options_advice(self) -> dict[str, Any]:
        try:
            from quant_platform.options.advice import AccountOptionsAdviceService

            result = AccountOptionsAdviceService(self.settings).generate(
                as_of=now_beijing().date(),
                max_workers=2,
                timeout_seconds=60,
                max_expirations_per_symbol=2,
            )
            payload = {
                "status": "success",
                "generated_at_beijing": result.generated_at_beijing,
                "position_count": result.position_count,
                "advice_count": result.advice_count,
                "error_count": result.error_count,
                "json_path": str(result.json_path),
                "markdown_path": str(result.markdown_path),
            }
            self.logger.info("daily_refresh.options_advice.success", **payload)
            self.logger.notice(
                "daily_refresh.options_advice.success",
                positions=result.position_count,
                advice=result.advice_count,
                errors=result.error_count,
            )
            return payload
        except Exception as exc:  # noqa: BLE001 - option data can be unavailable.
            self.logger.error("daily_refresh.options_advice.error", error=str(exc))
            self.logger.notice("daily_refresh.options_advice.error", error=str(exc))
            return {"status": "error", "error": str(exc)}

    def _run_macro_risk(self, *, pool_id: str, market_date: date) -> dict[str, Any]:
        try:
            from quant_platform.services.macro_risk import MacroRiskService

            symbols = self._symbols_for_macro_news(pool_id)
            result = MacroRiskService(self.settings).generate(
                market_date_us=market_date,
                symbols=symbols,
                news_limit_per_symbol=3,
            )
            payload = {
                "status": "success",
                "generated_at_beijing": result.generated_at_beijing,
                "market_date_us": result.market_date_us,
                "risk_state": result.risk_state,
                "sentiment_state": result.sentiment_state,
                "news_item_count": result.news_item_count,
                "warnings": result.warnings,
                "json_path": str(result.json_path),
                "markdown_path": str(result.markdown_path),
            }
            self.logger.info("daily_refresh.macro_risk.success", **_loggable(payload))
            self.logger.notice(
                "daily_refresh.macro_risk.success",
                risk_state=result.risk_state,
                sentiment=result.sentiment_state,
                news=result.news_item_count,
            )
            return payload
        except Exception as exc:  # noqa: BLE001
            self.logger.error("daily_refresh.macro_risk.error", error=str(exc))
            self.logger.notice("daily_refresh.macro_risk.error", error=str(exc))
            return {"status": "error", "error": str(exc)}

    def _symbols_for_macro_news(self, pool_id: str) -> list[str]:
        symbols: list[str] = []
        account_report = self.settings.storage.processed_dir.parent / "reports" / "account_health"
        candidates = sorted(account_report.glob("account_health_*.json"))
        if candidates:
            try:
                payload = json.loads(candidates[-1].read_text(encoding="utf-8"))
                assessment = payload.get("risk_assessment") if isinstance(payload.get("risk_assessment"), dict) else {}
                positions = assessment.get("positions") if isinstance(assessment.get("positions"), list) else []
                symbols.extend(str(item.get("symbol") or "") for item in positions if isinstance(item, dict))
            except (OSError, json.JSONDecodeError):
                pass
        if not symbols:
            pool_path = self.artifacts.layout.storage.reference_dir / "system" / "stock_pools"
            matches = list(pool_path.glob(f"*/{pool_id}.json"))
            if matches:
                try:
                    payload = json.loads(matches[0].read_text(encoding="utf-8"))
                    raw_symbols = payload.get("symbols") if isinstance(payload.get("symbols"), list) else []
                    symbols.extend(str(symbol) for symbol in raw_symbols[:8])
                except (OSError, json.JSONDecodeError):
                    pass
        return symbols[:8]

    def _run_daily_report(self, *, pool_id: str, market_date: date) -> dict[str, Any]:
        try:
            from quant_platform.services.daily_report import DailyReportService

            self.logger.notice("daily_refresh.daily_report.start", pool_id=pool_id, market_date_us=market_date.isoformat())
            result = DailyReportService(self.settings).generate(pool_id=pool_id, market_date_us=market_date)
            payload = {
                "status": "success",
                "generated_at_beijing": result.generated_at_beijing,
                "scanner_count": result.scanner_count,
                "market_events_count": result.market_events_count,
                "path": str(result.path),
            }
            self.logger.info("daily_refresh.daily_report.success", **payload)
            self.logger.notice("daily_refresh.daily_report.success", path=str(result.path))
            return payload
        except Exception as exc:  # noqa: BLE001
            self.logger.error("daily_refresh.daily_report.error", error=str(exc))
            self.logger.notice("daily_refresh.daily_report.error", error=str(exc))
            return {"status": "error", "error": str(exc)}

    def _run_ai_dashboard(self, *, pool_id: str) -> dict[str, Any]:
        try:
            from quant_platform.services.ai_analysis import AutomatedAIAnalysisService

            result = AutomatedAIAnalysisService(self.settings).analyze_dashboard(
                pool_id=pool_id,
                use_model=self.settings.scheduler.daily_refresh_ai_use_model,
            )
            payload = {
                "status": "success",
                "generated_at_beijing": result.generated_at_beijing,
                "snapshot_count": result.snapshot_count,
                "model_status": result.model_status,
                "warnings": result.warnings,
                "json_path": str(result.json_path),
                "markdown_path": str(result.markdown_path),
            }
            self.logger.info("daily_refresh.ai_dashboard.success", **_loggable(payload))
            self.logger.notice(
                "daily_refresh.ai_dashboard.success",
                snapshots=result.snapshot_count,
                model_status=result.model_status,
            )
            return payload
        except Exception as exc:  # noqa: BLE001
            self.logger.error("daily_refresh.ai_dashboard.error", error=str(exc))
            self.logger.notice("daily_refresh.ai_dashboard.error", error=str(exc))
            return {"status": "error", "error": str(exc)}

    def _run_ai_account_health(self) -> dict[str, Any]:
        try:
            from quant_platform.services.ai_analysis import AutomatedAIAnalysisService

            result = AutomatedAIAnalysisService(self.settings).analyze_latest_account_health(
                use_model=self.settings.scheduler.daily_refresh_ai_use_model,
            )
            payload = _ai_interpretation_payload(result)
            self.logger.notice("daily_refresh.ai_account_health.success", model_status=result.model_status)
            return payload
        except Exception as exc:  # noqa: BLE001
            self.logger.error("daily_refresh.ai_account_health.error", error=str(exc))
            self.logger.notice("daily_refresh.ai_account_health.error", error=str(exc))
            return {"status": "error", "error": str(exc)}

    def _run_ai_options_advice(self) -> dict[str, Any]:
        try:
            from quant_platform.services.ai_analysis import AutomatedAIAnalysisService

            result = AutomatedAIAnalysisService(self.settings).analyze_latest_options_advice(
                use_model=self.settings.scheduler.daily_refresh_ai_use_model,
            )
            payload = _ai_interpretation_payload(result)
            self.logger.notice("daily_refresh.ai_options_advice.success", model_status=result.model_status)
            return payload
        except Exception as exc:  # noqa: BLE001
            self.logger.error("daily_refresh.ai_options_advice.error", error=str(exc))
            self.logger.notice("daily_refresh.ai_options_advice.error", error=str(exc))
            return {"status": "error", "error": str(exc)}

    def _summary_path(self, pool_id: str, market_date_us: date) -> Path:
        return self.settings.storage.reference_dir / "system" / "daily_refresh" / f"{pool_id}_{market_date_us.isoformat()}.json"

    def _write_summary(self, result: DailyRefreshResult) -> None:
        result.summary_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "generated_at_beijing": result.generated_at_beijing,
            "timezone": "Asia/Shanghai",
            "market_date_us": result.market_date_us.isoformat(),
            "market_timezone": "America/New_York",
            "pool_id": result.pool_id,
            "dashboard_path": str(result.dashboard_path),
            "snapshot_count": result.snapshot_count,
            "market_events_count": result.market_events_count,
            "history": result.history,
            "supplemental_outputs": result.supplemental_outputs or {},
        }
        result.summary_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _history_status(cursor: str | None, market_date_us: date) -> str:
    if cursor is None:
        return "empty"
    try:
        return "success" if date.fromisoformat(cursor) >= market_date_us else "empty"
    except ValueError:
        return "empty"


def _count_history_status(history_results: dict[str, dict[str, Any]], status: str) -> int:
    return sum(1 for item in history_results.values() if item.get("status") == status)


def _ai_interpretation_payload(result: Any) -> dict[str, Any]:
    payload = {
        "status": "success",
        "generated_at_beijing": result.generated_at_beijing,
        "scenario": result.scenario,
        "target_id": result.target_id,
        "model_status": result.model_status,
        "warnings": result.warnings,
        "source_paths": [str(path) for path in result.source_paths],
        "json_path": str(result.json_path),
        "markdown_path": str(result.markdown_path),
    }
    return payload


def _loggable(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key != "warnings"}


def _summarize_supplemental(outputs: dict[str, Any]) -> str:
    if not outputs:
        return "none"
    parts = []
    for name, payload in outputs.items():
        status = payload.get("status") if isinstance(payload, dict) else "unknown"
        parts.append(f"{name}:{status}")
    return ",".join(parts)
