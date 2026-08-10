"""Public signing-key registry with append-only lifecycle events.

Only Ed25519 public keys are stored here. Private signing material must remain in
an external secret store or deployment environment.
"""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


class SigningKeyRegistryError(RuntimeError):
    """Raised when a signing-key lifecycle or integrity rule is violated."""


def signing_key_id(public_key_b64: str) -> str:
    raw = base64.b64decode(public_key_b64, validate=True)
    if len(raw) != 32:
        raise ValueError("Ed25519 public key must decode to exactly 32 raw bytes")
    Ed25519PublicKey.from_public_bytes(raw)
    return hashlib.sha256(raw).hexdigest()[:24]


class SigningKeyRegistry:
    """SQLite registry for public signing keys and append-only lifecycle events."""

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
                CREATE TABLE IF NOT EXISTS signing_keys (
                    key_id TEXT PRIMARY KEY,
                    public_key_b64 TEXT NOT NULL,
                    algorithm TEXT NOT NULL,
                    label TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS signing_key_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(key_id) REFERENCES signing_keys(key_id)
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_signing_key_events_key ON signing_key_events(key_id, event_id)"
            )

    def status(
        self,
        key_id: str,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> str | None:
        owns_connection = connection is None
        current = connection or self._connect()
        try:
            row = current.execute(
                """
                SELECT event_type
                FROM signing_key_events
                WHERE key_id = ?
                ORDER BY event_id DESC
                LIMIT 1
                """,
                (key_id,),
            ).fetchone()
            if row is None:
                return None
            return {
                "registered": "registered",
                "activated": "active",
                "retired": "retired",
                "revoked": "revoked",
            }[row["event_type"]]
        finally:
            if owns_connection:
                current.close()

    def register(
        self,
        public_key_b64: str,
        *,
        label: str | None = None,
        activate: bool = True,
    ) -> dict[str, Any]:
        key_id = signing_key_id(public_key_b64)
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT public_key_b64 FROM signing_keys WHERE key_id = ?",
                (key_id,),
            ).fetchone()
            if existing and existing["public_key_b64"] != public_key_b64:
                raise SigningKeyRegistryError("key_id collision with different public key material")
            if not existing:
                connection.execute(
                    """
                    INSERT INTO signing_keys (key_id, public_key_b64, algorithm, label)
                    VALUES (?, ?, 'Ed25519', ?)
                    """,
                    (key_id, public_key_b64, label),
                )
                connection.execute(
                    """
                    INSERT INTO signing_key_events (key_id, event_type, metadata_json)
                    VALUES (?, 'registered', ?)
                    """,
                    (key_id, json.dumps({"label": label}, sort_keys=True)),
                )
            if activate and self.status(key_id, connection=connection) != "active":
                connection.execute(
                    "INSERT INTO signing_key_events (key_id, event_type) VALUES (?, 'activated')",
                    (key_id,),
                )
        record = self.get(key_id)
        if record is None:  # pragma: no cover - defensive database guard
            raise SigningKeyRegistryError("registered key could not be read back")
        return record

    def transition(
        self,
        key_id: str,
        event_type: str,
        *,
        reason: str | None = None,
    ) -> dict[str, Any]:
        if event_type not in {"activated", "retired", "revoked"}:
            raise ValueError("event_type must be activated, retired, or revoked")
        if self.get(key_id) is None:
            raise KeyError(key_id)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO signing_key_events (key_id, event_type, metadata_json)
                VALUES (?, ?, ?)
                """,
                (key_id, event_type, json.dumps({"reason": reason}, sort_keys=True)),
            )
        record = self.get(key_id)
        if record is None:  # pragma: no cover
            raise SigningKeyRegistryError("transitioned key could not be read back")
        return record

    def get(self, key_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT key_id, public_key_b64, algorithm, label, created_at
                FROM signing_keys
                WHERE key_id = ?
                """,
                (key_id,),
            ).fetchone()
            if row is None:
                return None
            status = self.status(key_id, connection=connection)
        return {**dict(row), "status": status}

    def list(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT key_id FROM signing_keys ORDER BY created_at ASC, key_id ASC"
            ).fetchall()
        return [record for row in rows if (record := self.get(row["key_id"])) is not None]

    def events(self, key_id: str) -> list[dict[str, Any]]:
        if self.get(key_id) is None:
            raise KeyError(key_id)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT event_id, event_type, metadata_json, created_at
                FROM signing_key_events
                WHERE key_id = ?
                ORDER BY event_id ASC
                """,
                (key_id,),
            ).fetchall()
        return [
            {
                "event_id": row["event_id"],
                "event_type": row["event_type"],
                "metadata": json.loads(row["metadata_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def assert_can_sign(self, key_id: str) -> dict[str, Any]:
        record = self.get(key_id)
        if record is None:
            raise SigningKeyRegistryError(f"signing key {key_id} is not registered")
        if record["status"] != "active":
            raise SigningKeyRegistryError(
                f"signing key {key_id} is {record['status']}, not active"
            )
        return record
