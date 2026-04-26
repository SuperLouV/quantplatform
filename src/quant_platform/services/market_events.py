"""Market-wide event calendar service."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from quant_platform.clients import CensusCalendarClient, FedCalendarClient, FredClient
from quant_platform.config import Settings
from quant_platform.core.market_events import MarketEvent
from quant_platform.services.bootstrap import bootstrap_local_state
from quant_platform.services.operation_log import OperationLogger, operation_log_root


@dataclass(slots=True)
class MarketEventUpdateResult:
    path: Path
    events: list[MarketEvent]
    provider_counts: dict[str, int]


class MarketEventService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.artifacts = bootstrap_local_state(settings)
        self.fed = FedCalendarClient.from_data_config(settings.data)
        self.census = CensusCalendarClient.from_data_config(settings.data)
        self.fred = FredClient.from_data_config(settings.data)
        self.logger = OperationLogger(operation_log_root(settings), "market_events")

    def load_events(self, *, start: date | None = None, end: date | None = None) -> list[dict[str, object]]:
        path = self.events_path()
        if not path.exists():
            self.update_events(start=start, end=end)
        payload = json.loads(path.read_text(encoding="utf-8"))
        events = payload.get("events", [])
        return _filter_event_payloads(events, start=start, end=end)

    def update_events(self, *, start: date | None = None, end: date | None = None) -> MarketEventUpdateResult:
        today = datetime.now(tz=UTC).date()
        start = start or today - timedelta(days=90)
        end = end or today + timedelta(days=180)
        years = sorted({start.year, end.year, today.year, today.year + 1})

        events: list[MarketEvent] = []
        provider_counts: dict[str, int] = {}
        self.logger.info(
            "market_events.update.start",
            start=start.isoformat(),
            end=end.isoformat(),
            fred_enabled=bool(self.settings.data.fred_api_key),
        )

        for provider_name, fetch in (
            ("fed", lambda: self.fed.fetch_fomc_events(years)),
            ("census", self.census.fetch_events),
            ("fred", lambda: self.fred.fetch_release_events(start=start, end=end)),
        ):
            try:
                self.logger.info("market_events.provider.start", provider=provider_name)
                provider_events = fetch()
                self.logger.info("market_events.provider.success", provider=provider_name, events=len(provider_events))
            except Exception as exc:  # noqa: BLE001 - one provider should not break the calendar.
                self.logger.error("market_events.provider.error", provider=provider_name, error=str(exc))
                provider_events = [
                    MarketEvent(
                        event_id=f"{provider_name}:error:{today.isoformat()}",
                        title=f"{provider_name} 事件源暂不可用",
                        category="data_quality",
                        source=provider_name,
                        event_time=datetime.combine(today, datetime.min.time(), tzinfo=UTC),
                        importance="low",
                        status="estimated",
                        detail=str(exc),
                    )
                ]
            provider_counts[provider_name] = len(provider_events)
            events.extend(provider_events)

        events = _dedupe_events(events)
        payload_events = [event.to_dict() for event in sorted(events, key=lambda item: item.event_time)]
        path = self.events_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "generated_at": datetime.now(tz=UTC).isoformat(),
                    "window": {"start": start.isoformat(), "end": end.isoformat()},
                    "provider_counts": provider_counts,
                    "events": payload_events,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        self.logger.info(
            "market_events.update.success",
            path=str(path),
            events=len(events),
            provider_counts=provider_counts,
        )
        return MarketEventUpdateResult(path=path, events=events, provider_counts=provider_counts)

    def events_path(self) -> Path:
        return self.artifacts.layout.reference_file_path("system", "market_events", "json")


def _dedupe_events(events: list[MarketEvent]) -> list[MarketEvent]:
    seen: dict[str, MarketEvent] = {}
    for event in events:
        seen[event.event_id] = event
    return list(seen.values())


def _filter_event_payloads(
    events: list[dict[str, object]],
    *,
    start: date | None,
    end: date | None,
) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for event in events:
        raw_time = event.get("event_time")
        if not raw_time:
            continue
        event_date = datetime.fromisoformat(str(raw_time)).date()
        if start and event_date < start:
            continue
        if end and event_date > end:
            continue
        result.append(event)
    return result
