"""In-process scheduler for UI server background jobs."""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from datetime import date, time
from pathlib import Path
from typing import Any

from quant_platform.config import Settings
from quant_platform.services.daily_refresh import DailyRefreshService
from quant_platform.services.operation_log import OperationLogger, operation_log_root
from quant_platform.time_utils import latest_us_weekday, now_beijing


@dataclass(slots=True)
class SchedulerRunState:
    running: bool = False
    last_started_at_beijing: str | None = None
    last_finished_at_beijing: str | None = None
    last_status: str | None = None
    last_error: str | None = None
    last_market_date_us: str | None = None
    last_summary_path: str | None = None


class DailyRefreshScheduler:
    def __init__(self, settings: Settings, *, project_root: Path) -> None:
        self.settings = settings
        self.project_root = project_root
        self.logger = OperationLogger(operation_log_root(settings), "server_scheduler")
        self.service = DailyRefreshService(settings)
        self.state = SchedulerRunState()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._attempted_keys: set[str] = set()
        self._skipped_keys: set[str] = set()

    def start(self) -> None:
        if not self.settings.scheduler.enabled:
            self.logger.info("scheduler.disabled")
            return
        if self._thread and self._thread.is_alive():
            return
        scheduled_time = _parse_time(self.settings.scheduler.daily_refresh_time_beijing)
        self._thread = threading.Thread(
            target=self._loop,
            name="quantplatform-daily-refresh-scheduler",
            daemon=True,
            args=(scheduled_time,),
        )
        self._thread.start()
        self.logger.info(
            "scheduler.start",
            daily_refresh_time_beijing=self.settings.scheduler.daily_refresh_time_beijing,
            pool=self.settings.scheduler.daily_refresh_pool,
            workers=self.settings.scheduler.daily_refresh_workers,
            poll_interval_seconds=self.settings.scheduler.poll_interval_seconds,
        )

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        self.logger.info("scheduler.stop")

    def status(self) -> dict[str, Any]:
        thread_alive = bool(self._thread and self._thread.is_alive())
        return {
            "enabled": self.settings.scheduler.enabled,
            "thread_alive": thread_alive,
            "daily_refresh_time_beijing": self.settings.scheduler.daily_refresh_time_beijing,
            "daily_refresh_pool": self.settings.scheduler.daily_refresh_pool,
            "daily_refresh_workers": self.settings.scheduler.daily_refresh_workers,
            "daily_refresh_update_events": self.settings.scheduler.daily_refresh_update_events,
            "poll_interval_seconds": self.settings.scheduler.poll_interval_seconds,
            "state": {
                "running": self.state.running,
                "last_started_at_beijing": self.state.last_started_at_beijing,
                "last_finished_at_beijing": self.state.last_finished_at_beijing,
                "last_status": self.state.last_status,
                "last_error": self.state.last_error,
                "last_market_date_us": self.state.last_market_date_us,
                "last_summary_path": self.state.last_summary_path,
            },
            "latest_summary": self._latest_summary(),
        }

    def _loop(self, scheduled_time: time) -> None:
        while not self._stop_event.is_set():
            try:
                self._tick(scheduled_time)
            except Exception as exc:  # noqa: BLE001 - scheduler must keep running after unexpected errors.
                self.logger.error("scheduler.tick.error", error=str(exc))
            self._stop_event.wait(max(5, self.settings.scheduler.poll_interval_seconds))

    def _tick(self, scheduled_time: time) -> None:
        current = now_beijing()
        if current.time() < scheduled_time:
            return

        market_date = latest_us_weekday(current)
        run_key = f"{current.date().isoformat()}:{market_date.isoformat()}"
        if run_key in self._attempted_keys:
            return

        pool_path = self._pool_path()
        summary_path = self._summary_path(pool_path, market_date)
        if self._summary_is_complete(summary_path):
            if run_key not in self._skipped_keys:
                self._skipped_keys.add(run_key)
                self.logger.info(
                    "scheduler.daily_refresh.skipped",
                    reason="summary_complete",
                    market_date_us=market_date.isoformat(),
                    summary_path=str(summary_path),
                )
            self._attempted_keys.add(run_key)
            return

        self._attempted_keys.add(run_key)
        self._run_daily_refresh(pool_path=pool_path, market_date=market_date)

    def _run_daily_refresh(self, *, pool_path: Path, market_date: date) -> None:
        if not self._lock.acquire(blocking=False):
            self.logger.info("scheduler.daily_refresh.skipped", reason="already_running")
            return

        started_at = now_beijing()
        self.state.running = True
        self.state.last_started_at_beijing = started_at.isoformat()
        self.state.last_finished_at_beijing = None
        self.state.last_status = "running"
        self.state.last_error = None
        self.state.last_market_date_us = market_date.isoformat()
        self.logger.info(
            "scheduler.daily_refresh.start",
            market_date_us=market_date.isoformat(),
            pool_path=str(pool_path),
            workers=self.settings.scheduler.daily_refresh_workers,
            update_events=self.settings.scheduler.daily_refresh_update_events,
        )

        try:
            result = self.service.run(
                pool_path=pool_path,
                market_date_us=market_date,
                workers=self.settings.scheduler.daily_refresh_workers,
                update_events=self.settings.scheduler.daily_refresh_update_events,
            )
            self.state.last_status = "success"
            self.state.last_summary_path = str(result.summary_path)
            self.logger.info(
                "scheduler.daily_refresh.success",
                market_date_us=market_date.isoformat(),
                summary_path=str(result.summary_path),
                snapshot_count=result.snapshot_count,
                market_events_count=result.market_events_count,
            )
        except Exception as exc:
            self.state.last_status = "error"
            self.state.last_error = str(exc)
            self.logger.error(
                "scheduler.daily_refresh.error",
                market_date_us=market_date.isoformat(),
                pool_path=str(pool_path),
                error=str(exc),
            )
        finally:
            self.state.running = False
            self.state.last_finished_at_beijing = now_beijing().isoformat()
            self._lock.release()

    def _pool_path(self) -> Path:
        path = Path(self.settings.scheduler.daily_refresh_pool)
        if path.is_absolute():
            return path
        return self.project_root / path

    def _summary_path(self, pool_path: Path, market_date: date) -> Path:
        payload = json.loads(pool_path.read_text(encoding="utf-8"))
        pool_id = str(payload["pool_id"])
        return self.settings.storage.reference_dir / "system" / "daily_refresh" / f"{pool_id}_{market_date.isoformat()}.json"

    def _summary_is_complete(self, path: Path) -> bool:
        if not path.exists():
            return False
        payload = json.loads(path.read_text(encoding="utf-8"))
        history = payload.get("history")
        if not isinstance(history, dict):
            return False
        return all(isinstance(item, dict) and item.get("status") == "success" for item in history.values())

    def _latest_summary(self) -> dict[str, Any] | None:
        try:
            pool_payload = json.loads(self._pool_path().read_text(encoding="utf-8"))
            pool_id = str(pool_payload["pool_id"])
            base = self.settings.storage.reference_dir / "system" / "daily_refresh"
            matches = sorted(base.glob(f"{pool_id}_*.json"))
            if not matches:
                return None
            path = matches[-1]
            payload = json.loads(path.read_text(encoding="utf-8"))
            history = payload.get("history")
            history_items = history.values() if isinstance(history, dict) else []
            history_success = sum(1 for item in history_items if isinstance(item, dict) and item.get("status") == "success")
            history_empty = sum(1 for item in history_items if isinstance(item, dict) and item.get("status") == "empty")
            history_error = sum(1 for item in history_items if isinstance(item, dict) and item.get("status") == "error")
            return {
                "path": str(path),
                "generated_at_beijing": payload.get("generated_at_beijing"),
                "market_date_us": payload.get("market_date_us"),
                "market_timezone": payload.get("market_timezone"),
                "pool_id": payload.get("pool_id"),
                "snapshot_count": payload.get("snapshot_count"),
                "market_events_count": payload.get("market_events_count"),
                "history_success": history_success,
                "history_empty": history_empty,
                "history_error": history_error,
            }
        except Exception as exc:  # noqa: BLE001 - status endpoint should degrade without breaking UI.
            self.logger.error("scheduler.latest_summary.error", error=str(exc))
            return None


def _parse_time(value: str) -> time:
    hour_text, minute_text = value.split(":", 1)
    return time(hour=int(hour_text), minute=int(minute_text))
