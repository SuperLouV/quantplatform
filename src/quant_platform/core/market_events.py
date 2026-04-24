"""Market-wide event models for reports and the local UI."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal


EventImportance = Literal["high", "medium", "low"]
EventStatus = Literal["scheduled", "released", "estimated"]


@dataclass(slots=True)
class MarketEvent:
    event_id: str
    title: str
    category: str
    source: str
    event_time: datetime
    importance: EventImportance
    affected_assets: list[str] = field(default_factory=list)
    status: EventStatus = "scheduled"
    detail: str | None = None
    url: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "event_id": self.event_id,
            "title": self.title,
            "category": self.category,
            "source": self.source,
            "event_time": self.event_time.isoformat(),
            "importance": self.importance,
            "affected_assets": self.affected_assets,
            "status": self.status,
            "detail": self.detail,
            "url": self.url,
        }
