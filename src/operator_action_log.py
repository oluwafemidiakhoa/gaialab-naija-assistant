"""Tamper-evident append-only operator action logging for GaiaLab Trust Rail."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Mapping
import uuid

OPERATOR_ACTION_LOG_VERSION = "gaialab-naija-operator-actions/0.1.0"
GENESIS_HASH = "0" * 64
_FORBIDDEN_METADATA_PARTS = ("password", "secret", "token", "api_key", "private_key", "database_url")


class OperatorActionLogError(RuntimeError):
    """Raised when operator action integrity or privacy rules are violated."""


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _sha256(payload: Any) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _target_hash(target_id: str) -> str:
    if not target_id:
        raise ValueError("target_id must not be empty")
    return hashlib.sha256(target_id.encode("utf-8")).hexdigest()


def _reject_secret_metadata(value: Any, *, path: str = "metadata") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            lowered = str(key).lower()
            if any(part in lowered for part in _FORBIDDEN_METADATA_PARTS):
                raise OperatorActionLogError(f"secret-like metadata field is not allowed: {path}.{key}")
            _reject_secret_metadata(child, path=f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _reject_secret_metadata(child, path=f"{path}[{index}]")


def build_action(
    *,
    operator_id: str,
    key_id: str | None,
    action_type: str,
    target_type: str,
    target_id: str,
    metadata: Mapping[str, Any] | None,
    previous_action_hash: str,
    action_id: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    if not operator_id or not action_type or not target_type:
        raise ValueError("operator_id, action_type, and target_type are required")
    payload = dict(metadata or {})
    _reject_secret_metadata(payload)
    action_id = action_id or f"opact_{uuid.uuid4().hex}"
    created_at = created_at or datetime.now(timezone.utc).isoformat()
    core = {
        "version": OPERATOR_ACTION_LOG_VERSION,
        "action_id": action_id,
        "operator_id": operator_id,
        "key_id": key_id,
        "action_type": action_type,
        "target_type": target_type,
        "target_id_sha256": _target_hash(target_id),
        "metadata": payload,
        "previous_action_hash": previous_action_hash,
        "created_at": created_at,
    }
    return {**core, "action_hash": _sha256(core)}


def _verify_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    previous = GENESIS_HASH
    for index, row in enumerate(rows):
        core = {
            "version": row["version"],
            "action_id": row["action_id"],
            "operator_id": row["operator_id"],
            "key_id": row.get("key_id"),
            "action_type": row["action_type"],
            "target_type": row["target_type"],
            "target_id_sha256": row["target_id_sha256"],
            "metadata": row["metadata"],
            "previous_action_hash": row["previous_action_hash"],
            "created_at": row["created_at"],
        }
        expected = _sha256(core)
        if row["previous_action_hash"] != previous:
            return {"valid": False, "reason": "previous_hash_mismatch", "index": index}
        if row["action_hash"] != expected:
            return {"valid": False, "reason": "action_hash_mismatch", "index": index}
        previous = row["action_hash"]
    return {"valid": True, "reason": "operator_action_chain_valid", "count": len(rows), "head": previous}


class OperatorActionLog:
    """SQLite operator action ledger for local development and tests."""

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
                "CREATE TABLE IF NOT EXISTS operator_action_log_heads (stream_id TEXT PRIMARY KEY, last_action_hash TEXT NOT NULL)"
            )
            connection.execute(
                "INSERT OR IGNORE INTO operator_action_log_heads (stream_id, last_action_hash) VALUES ('global', ?)",
                (GENESIS_HASH,),
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS operator_actions (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    action_id TEXT NOT NULL UNIQUE,
                    operator_id TEXT NOT NULL,
                    key_id TEXT,
                    action_type TEXT NOT NULL,
                    target_type TEXT NOT NULL,
                    target_id_sha256 TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    previous_action_hash TEXT NOT NULL,
                    action_hash TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL
                )
                """
            )

    def append(self, *, operator_id: str, key_id: str | None, action_type: str, target_type: str, target_id: str, metadata: Mapping[str, Any] | None = None) -> dict[str, Any]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            previous = connection.execute(
                "SELECT last_action_hash FROM operator_action_log_heads WHERE stream_id='global'"
            ).fetchone()["last_action_hash"]
            action = build_action(
                operator_id=operator_id,
                key_id=key_id,
                action_type=action_type,
                target_type=target_type,
                target_id=target_id,
                metadata=metadata,
                previous_action_hash=previous,
            )
            connection.execute(
                """
                INSERT INTO operator_actions (
                    action_id, operator_id, key_id, action_type, target_type,
                    target_id_sha256, metadata_json, previous_action_hash,
                    action_hash, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    action["action_id"], action["operator_id"], action["key_id"], action["action_type"],
                    action["target_type"], action["target_id_sha256"], _canonical_json(action["metadata"]),
                    action["previous_action_hash"], action["action_hash"], action["created_at"],
                ),
            )
            connection.execute(
                "UPDATE operator_action_log_heads SET last_action_hash=? WHERE stream_id='global'",
                (action["action_hash"],),
            )
            connection.commit()
            return action
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def list(self, *, limit: int = 1000) -> list[dict[str, Any]]:
        if not 1 <= limit <= 10000:
            raise ValueError("limit must be between 1 and 10000")
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM operator_actions ORDER BY event_id LIMIT ?", (limit,)
            ).fetchall()
        return [
            {
                "event_id": row["event_id"], "version": OPERATOR_ACTION_LOG_VERSION,
                "action_id": row["action_id"], "operator_id": row["operator_id"], "key_id": row["key_id"],
                "action_type": row["action_type"], "target_type": row["target_type"],
                "target_id_sha256": row["target_id_sha256"], "metadata": json.loads(row["metadata_json"]),
                "previous_action_hash": row["previous_action_hash"], "action_hash": row["action_hash"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def verify_chain(self) -> dict[str, Any]:
        return _verify_rows(self.list(limit=10000))


class NeonOperatorActionLog:
    """Neon operator action ledger using row locking for a single global chain."""

    def __init__(self, backend):
        self.backend = backend

    def append(self, *, operator_id: str, key_id: str | None, action_type: str, target_type: str, target_id: str, metadata: Mapping[str, Any] | None = None) -> dict[str, Any]:
        with self.backend.connect() as connection:
            head = connection.execute(
                "SELECT last_action_hash FROM operator_action_log_heads WHERE stream_id='global' FOR UPDATE"
            ).fetchone()
            if head is None:
                raise OperatorActionLogError("operator action log head is missing")
            action = build_action(
                operator_id=operator_id,
                key_id=key_id,
                action_type=action_type,
                target_type=target_type,
                target_id=target_id,
                metadata=metadata,
                previous_action_hash=head["last_action_hash"],
            )
            connection.execute(
                """
                INSERT INTO operator_actions (
                    action_id, operator_id, key_id, action_type, target_type,
                    target_id_sha256, metadata_json, previous_action_hash,
                    action_hash, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::timestamptz)
                """,
                (
                    action["action_id"], action["operator_id"], action["key_id"], action["action_type"],
                    action["target_type"], action["target_id_sha256"], _canonical_json(action["metadata"]),
                    action["previous_action_hash"], action["action_hash"], action["created_at"],
                ),
            )
            connection.execute(
                "UPDATE operator_action_log_heads SET last_action_hash=%s WHERE stream_id='global'",
                (action["action_hash"],),
            )
        return action

    def list(self, *, limit: int = 1000) -> list[dict[str, Any]]:
        if not 1 <= limit <= 10000:
            raise ValueError("limit must be between 1 and 10000")
        with self.backend.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM operator_actions ORDER BY event_id LIMIT %s", (limit,)
            ).fetchall()
        return [
            {
                "event_id": row["event_id"], "version": OPERATOR_ACTION_LOG_VERSION,
                "action_id": row["action_id"], "operator_id": row["operator_id"], "key_id": row["key_id"],
                "action_type": row["action_type"], "target_type": row["target_type"],
                "target_id_sha256": row["target_id_sha256"], "metadata": json.loads(row["metadata_json"]),
                "previous_action_hash": row["previous_action_hash"], "action_hash": row["action_hash"],
                "created_at": row["created_at"].isoformat() if hasattr(row["created_at"], "isoformat") else str(row["created_at"]),
            }
            for row in rows
        ]

    def verify_chain(self) -> dict[str, Any]:
        return _verify_rows(self.list(limit=10000))
