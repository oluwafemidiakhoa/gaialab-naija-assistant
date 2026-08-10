"""Append-only audit export lifecycle registry for GaiaLab Naija Trust Rail."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Mapping


class AuditLifecycleError(RuntimeError):
    """Raised when audit-export lifecycle integrity rules are violated."""


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _sha256(payload: Any) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


class AuditLifecycleStore:
    """Record immutable export metadata and append-only lifecycle events."""

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
                CREATE TABLE IF NOT EXISTS audit_exports (
                    package_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    manifest_sha256 TEXT NOT NULL,
                    manifest_json TEXT NOT NULL,
                    retention_until TEXT,
                    created_by_key_id TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_export_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    package_id TEXT NOT NULL,
                    actor_type TEXT NOT NULL,
                    actor_id TEXT,
                    event_type TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(package_id) REFERENCES audit_exports(package_id)
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_audit_export_events ON audit_export_events(package_id, event_id)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_audit_exports_tenant ON audit_exports(tenant_id, created_at)"
            )

    def register_export(
        self,
        package: Mapping[str, Any],
        *,
        tenant_id: str,
        created_by_key_id: str | None,
        retention_until: str | None = None,
    ) -> dict[str, Any]:
        manifest = dict(package.get("manifest") or {})
        package_id = str(manifest.get("package_id") or "")
        if not package_id:
            raise ValueError("audit package manifest is missing package_id")
        if manifest.get("tenant_id") != tenant_id:
            raise AuditLifecycleError("audit package tenant does not match lifecycle tenant")
        manifest_core = {key: value for key, value in manifest.items() if key != "generated_at"}
        manifest_sha256 = _sha256(manifest_core)
        manifest_json = _canonical_json(manifest)

        with self._connect() as connection:
            existing = connection.execute(
                "SELECT tenant_id, manifest_sha256 FROM audit_exports WHERE package_id = ?",
                (package_id,),
            ).fetchone()
            if existing:
                if existing["tenant_id"] != tenant_id or existing["manifest_sha256"] != manifest_sha256:
                    raise AuditLifecycleError("package_id already exists with different immutable export metadata")
            else:
                connection.execute(
                    """
                    INSERT INTO audit_exports (
                        package_id, tenant_id, manifest_sha256, manifest_json,
                        retention_until, created_by_key_id
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        package_id,
                        tenant_id,
                        manifest_sha256,
                        manifest_json,
                        retention_until,
                        created_by_key_id,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO audit_export_events (
                        package_id, actor_type, actor_id, event_type, metadata_json
                    ) VALUES (?, 'service_key', ?, 'export_registered', ?)
                    """,
                    (
                        package_id,
                        created_by_key_id,
                        _canonical_json({"retention_until": retention_until}),
                    ),
                )
        record = self.get(package_id)
        if record is None:  # pragma: no cover
            raise AuditLifecycleError("registered audit export could not be read back")
        return record

    def add_event(
        self,
        package_id: str,
        *,
        actor_type: str,
        actor_id: str | None,
        event_type: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if actor_type not in {"operator", "service_key", "system"}:
            raise ValueError("unsupported actor_type")
        if event_type not in {
            "legal_hold_placed",
            "legal_hold_released",
            "retention_extended",
            "reviewed",
            "exported",
            "retention_eligible",
        }:
            raise ValueError("unsupported audit lifecycle event_type")
        if self.get(package_id) is None:
            raise KeyError(package_id)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO audit_export_events (
                    package_id, actor_type, actor_id, event_type, metadata_json
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    package_id,
                    actor_type,
                    actor_id,
                    event_type,
                    _canonical_json(dict(metadata or {})),
                ),
            )
            if event_type == "retention_extended":
                retention_until = (metadata or {}).get("retention_until")
                if not retention_until:
                    raise ValueError("retention_extended requires retention_until")
                connection.execute(
                    "UPDATE audit_exports SET retention_until = ? WHERE package_id = ?",
                    (retention_until, package_id),
                )
        return self.get(package_id) or {}

    def get(self, package_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT package_id, tenant_id, manifest_sha256, manifest_json,
                       retention_until, created_by_key_id, created_at
                FROM audit_exports WHERE package_id = ?
                """,
                (package_id,),
            ).fetchone()
        if row is None:
            return None
        events = self.events(package_id)
        hold_active = False
        for event in events:
            if event["event_type"] == "legal_hold_placed":
                hold_active = True
            elif event["event_type"] == "legal_hold_released":
                hold_active = False
        return {
            "package_id": row["package_id"],
            "tenant_id": row["tenant_id"],
            "manifest_sha256": row["manifest_sha256"],
            "manifest": json.loads(row["manifest_json"]),
            "retention_until": row["retention_until"],
            "created_by_key_id": row["created_by_key_id"],
            "created_at": row["created_at"],
            "legal_hold_active": hold_active,
            "events": events,
        }

    def events(self, package_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT event_id, actor_type, actor_id, event_type, metadata_json, created_at
                FROM audit_export_events WHERE package_id = ? ORDER BY event_id ASC
                """,
                (package_id,),
            ).fetchall()
        return [
            {
                "event_id": row["event_id"],
                "actor_type": row["actor_type"],
                "actor_id": row["actor_id"],
                "event_type": row["event_type"],
                "metadata": json.loads(row["metadata_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def retention_status(self, package_id: str, *, now: datetime | None = None) -> dict[str, Any]:
        record = self.get(package_id)
        if record is None:
            raise KeyError(package_id)
        now = now or datetime.now(timezone.utc)
        retention_until = record["retention_until"]
        expired = False
        if retention_until:
            parsed = datetime.fromisoformat(retention_until.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            expired = now >= parsed
        eligible = bool(expired and not record["legal_hold_active"])
        return {
            "package_id": package_id,
            "retention_until": retention_until,
            "legal_hold_active": record["legal_hold_active"],
            "retention_expired": expired,
            "eligible_for_deletion": eligible,
        }
