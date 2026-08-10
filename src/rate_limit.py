"""SQLite fixed-window rate limiting for GaiaLab Trust Rail API keys."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import time


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    limit: int
    remaining: int
    reset_at: int


class FixedWindowRateLimiter:
    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS api_rate_windows (
                    key_id TEXT NOT NULL,
                    bucket_start INTEGER NOT NULL,
                    count INTEGER NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(key_id, bucket_start)
                )
                """
            )

    def consume(
        self,
        key_id: str,
        *,
        limit: int,
        window_seconds: int = 60,
        now: int | None = None,
    ) -> RateLimitDecision:
        if limit <= 0:
            raise ValueError("limit must be positive")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        current = int(time.time() if now is None else now)
        bucket_start = current - (current % window_seconds)
        reset_at = bucket_start + window_seconds
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT count FROM api_rate_windows WHERE key_id = ? AND bucket_start = ?",
                (key_id, bucket_start),
            ).fetchone()
            count = row["count"] if row else 0
            if count >= limit:
                return RateLimitDecision(False, limit, 0, reset_at)
            new_count = count + 1
            connection.execute(
                """
                INSERT INTO api_rate_windows (key_id, bucket_start, count, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(key_id, bucket_start)
                DO UPDATE SET count = excluded.count, updated_at = excluded.updated_at
                """,
                (
                    key_id,
                    bucket_start,
                    new_count,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
        return RateLimitDecision(True, limit, max(0, limit - new_count), reset_at)
