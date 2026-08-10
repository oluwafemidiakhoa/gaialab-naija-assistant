"""Append-only SQLite storage for tenant-scoped GaiaLab receipt envelopes."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Mapping


class ReceiptConflictError(RuntimeError):
    """Raised when an existing receipt ID is presented with different content or ownership."""


def _canonical_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


class ReceiptStore:
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
                CREATE TABLE IF NOT EXISTS verification_receipts (
                    verification_id TEXT PRIMARY KEY,
                    payload_sha256 TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    tenant_id TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(verification_receipts)").fetchall()
            }
            if "tenant_id" not in columns:
                connection.execute("ALTER TABLE verification_receipts ADD COLUMN tenant_id TEXT")
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_verification_receipts_tenant ON verification_receipts(tenant_id, created_at)"
            )

    def save(
        self,
        verification_id: str,
        envelope: Mapping[str, Any],
        *,
        tenant_id: str | None = None,
    ) -> bool:
        payload_json = _canonical_json(envelope)
        payload_sha256 = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT payload_sha256, tenant_id FROM verification_receipts WHERE verification_id = ?",
                (verification_id,),
            ).fetchone()
            if existing:
                if existing["payload_sha256"] != payload_sha256 or existing["tenant_id"] != tenant_id:
                    raise ReceiptConflictError(
                        f"verification_id {verification_id} already exists with different content or tenant ownership"
                    )
                return False
            connection.execute(
                """
                INSERT INTO verification_receipts
                    (verification_id, payload_sha256, payload_json, tenant_id)
                VALUES (?, ?, ?, ?)
                """,
                (verification_id, payload_sha256, payload_json, tenant_id),
            )
        return True

    def get(self, verification_id: str, *, tenant_id: str | None = None) -> dict[str, Any] | None:
        with self._connect() as connection:
            if tenant_id is None:
                row = connection.execute(
                    """
                    SELECT payload_json
                    FROM verification_receipts
                    WHERE verification_id = ? AND tenant_id IS NULL
                    """,
                    (verification_id,),
                ).fetchone()
            else:
                row = connection.execute(
                    """
                    SELECT payload_json
                    FROM verification_receipts
                    WHERE verification_id = ? AND tenant_id = ?
                    """,
                    (verification_id, tenant_id),
                ).fetchone()
        return json.loads(row["payload_json"]) if row else None

    def list_for_tenant(
        self,
        tenant_id: str,
        *,
        created_from: str | None = None,
        created_to: str | None = None,
        limit: int = 10000,
    ) -> list[dict[str, Any]]:
        """Return tenant-owned receipt records with storage integrity metadata."""
        if not tenant_id:
            raise ValueError("tenant_id must not be empty")
        if not 1 <= limit <= 10000:
            raise ValueError("limit must be between 1 and 10000")

        clauses = ["tenant_id = ?"]
        params: list[Any] = [tenant_id]
        if created_from:
            clauses.append("created_at >= ?")
            params.append(created_from)
        if created_to:
            clauses.append("created_at <= ?")
            params.append(created_to)
        params.append(limit)

        query = f"""
            SELECT verification_id, payload_sha256, payload_json, created_at
            FROM verification_receipts
            WHERE {' AND '.join(clauses)}
            ORDER BY created_at ASC, verification_id ASC
            LIMIT ?
        """
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()

        records: list[dict[str, Any]] = []
        for row in rows:
            envelope = json.loads(row["payload_json"])
            actual_sha256 = hashlib.sha256(
                _canonical_json(envelope).encode("utf-8")
            ).hexdigest()
            records.append(
                {
                    "verification_id": row["verification_id"],
                    "created_at": row["created_at"],
                    "payload_sha256": row["payload_sha256"],
                    "payload_integrity_valid": actual_sha256 == row["payload_sha256"],
                    "envelope": envelope,
                }
            )
        return records
