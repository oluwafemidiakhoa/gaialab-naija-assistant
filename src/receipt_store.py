"""Append-only SQLite storage for GaiaLab verification receipt envelopes."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Mapping


class ReceiptConflictError(RuntimeError):
    """Raised when an existing receipt ID is presented with different content."""


def _canonical_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


class ReceiptStore:
    def __init__(self, path: str | Path):
        self.path = str(path)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS verification_receipts (
                    verification_id TEXT PRIMARY KEY,
                    payload_sha256 TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def save(self, verification_id: str, envelope: Mapping[str, Any]) -> bool:
        payload_json = _canonical_json(envelope)
        payload_sha256 = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT payload_sha256 FROM verification_receipts WHERE verification_id = ?",
                (verification_id,),
            ).fetchone()
            if existing:
                if existing["payload_sha256"] != payload_sha256:
                    raise ReceiptConflictError(
                        f"verification_id {verification_id} already exists with different content"
                    )
                return False
            connection.execute(
                "INSERT INTO verification_receipts (verification_id, payload_sha256, payload_json) VALUES (?, ?, ?)",
                (verification_id, payload_sha256, payload_json),
            )
        return True

    def get(self, verification_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM verification_receipts WHERE verification_id = ?",
                (verification_id,),
            ).fetchone()
        return json.loads(row["payload_json"]) if row else None
