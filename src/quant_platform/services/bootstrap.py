"""Startup helpers that prepare local storage and state management."""

from __future__ import annotations

from dataclasses import dataclass

from quant_platform.config import Settings
from quant_platform.storage import DataLayout, SQLiteStateStore


@dataclass(slots=True)
class BootstrapArtifacts:
    layout: DataLayout
    state_store: SQLiteStateStore


def bootstrap_local_state(settings: Settings) -> BootstrapArtifacts:
    layout = DataLayout(settings.storage)
    layout.ensure()

    state_store = SQLiteStateStore(settings.storage.state_db)
    state_store.initialize()

    return BootstrapArtifacts(layout=layout, state_store=state_store)
