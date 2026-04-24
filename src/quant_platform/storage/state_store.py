"""SQLite-backed metadata store for incremental update state."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator


@dataclass(slots=True)
class UpdateCheckpoint:
    provider: str
    dataset: str
    symbol: str
    cursor: str | None
    last_success_at: datetime | None
    last_attempt_at: datetime | None
    status: str
    note: str | None = None


@dataclass(slots=True)
class UpdateRunRecord:
    provider: str
    dataset: str
    symbol: str
    started_at: datetime
    finished_at: datetime | None
    status: str
    rows_written: int = 0
    note: str | None = None


class SQLiteStateStore:
    """State ledger used by ingestion jobs to support restart-safe incremental updates."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS update_checkpoints (
                    provider TEXT NOT NULL,
                    dataset TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    cursor TEXT,
                    last_success_at TEXT,
                    last_attempt_at TEXT,
                    status TEXT NOT NULL,
                    note TEXT,
                    PRIMARY KEY (provider, dataset, symbol)
                );

                CREATE TABLE IF NOT EXISTS update_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    provider TEXT NOT NULL,
                    dataset TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    status TEXT NOT NULL,
                    rows_written INTEGER NOT NULL DEFAULT 0,
                    note TEXT
                );
                """
            )

    def get_checkpoint(self, provider: str, dataset: str, symbol: str) -> UpdateCheckpoint | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT provider, dataset, symbol, cursor, last_success_at, last_attempt_at, status, note
                FROM update_checkpoints
                WHERE provider = ? AND dataset = ? AND symbol = ?
                """,
                (provider, dataset, symbol),
            ).fetchone()
        if row is None:
            return None
        return UpdateCheckpoint(
            provider=row["provider"],
            dataset=row["dataset"],
            symbol=row["symbol"],
            cursor=row["cursor"],
            last_success_at=_parse_timestamp(row["last_success_at"]),
            last_attempt_at=_parse_timestamp(row["last_attempt_at"]),
            status=row["status"],
            note=row["note"],
        )

    def upsert_checkpoint(self, checkpoint: UpdateCheckpoint) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO update_checkpoints (
                    provider, dataset, symbol, cursor, last_success_at, last_attempt_at, status, note
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(provider, dataset, symbol) DO UPDATE SET
                    cursor = excluded.cursor,
                    last_success_at = excluded.last_success_at,
                    last_attempt_at = excluded.last_attempt_at,
                    status = excluded.status,
                    note = excluded.note
                """,
                (
                    checkpoint.provider,
                    checkpoint.dataset,
                    checkpoint.symbol,
                    checkpoint.cursor,
                    _format_timestamp(checkpoint.last_success_at),
                    _format_timestamp(checkpoint.last_attempt_at),
                    checkpoint.status,
                    checkpoint.note,
                ),
            )

    def record_run(self, record: UpdateRunRecord) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO update_runs (
                    provider, dataset, symbol, started_at, finished_at, status, rows_written, note
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.provider,
                    record.dataset,
                    record.symbol,
                    _format_timestamp(record.started_at),
                    _format_timestamp(record.finished_at),
                    record.status,
                    record.rows_written,
                    record.note,
                ),
            )

    def mark_attempt(
        self,
        provider: str,
        dataset: str,
        symbol: str,
        *,
        cursor: str | None = None,
        status: str = "running",
        note: str | None = None,
    ) -> None:
        existing = self.get_checkpoint(provider, dataset, symbol)
        self.upsert_checkpoint(
            UpdateCheckpoint(
                provider=provider,
                dataset=dataset,
                symbol=symbol,
                cursor=cursor if cursor is not None else (existing.cursor if existing else None),
                last_success_at=existing.last_success_at if existing else None,
                last_attempt_at=_utcnow(),
                status=status,
                note=note,
            )
        )

    def mark_success(
        self,
        provider: str,
        dataset: str,
        symbol: str,
        *,
        cursor: str | None,
        note: str | None = None,
    ) -> None:
        now = _utcnow()
        self.upsert_checkpoint(
            UpdateCheckpoint(
                provider=provider,
                dataset=dataset,
                symbol=symbol,
                cursor=cursor,
                last_success_at=now,
                last_attempt_at=now,
                status="success",
                note=note,
            )
        )

    def mark_failure(
        self,
        provider: str,
        dataset: str,
        symbol: str,
        *,
        cursor: str | None = None,
        note: str | None = None,
    ) -> None:
        existing = self.get_checkpoint(provider, dataset, symbol)
        self.upsert_checkpoint(
            UpdateCheckpoint(
                provider=provider,
                dataset=dataset,
                symbol=symbol,
                cursor=cursor if cursor is not None else (existing.cursor if existing else None),
                last_success_at=existing.last_success_at if existing else None,
                last_attempt_at=_utcnow(),
                status="failed",
                note=note,
            )
        )


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


def _format_timestamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC).isoformat()
    return value.isoformat()


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)
