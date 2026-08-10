"""Two-person destructive retention authorization for GaiaLab audit exports.

Deletion is deliberately limited to audit-export metadata and lifecycle events.
Underlying verification receipts are never deleted by this workflow.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Mapping

from src.receipt_signing import sign_receipt, verify_receipt_signature

RETENTION_DELETION_VERSION = "gaialab-naija-retention-deletion/0.1.0"
REQUIRED_APPROVALS = 2


class RetentionDeletionError(RuntimeError):
    """Raised when destructive-retention safety requirements are not satisfied."""


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _sha256(payload: Any) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _parse_time(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def build_eligibility_snapshot(record: Mapping[str, Any], status: Mapping[str, Any]) -> dict[str, Any]:
    events = list(record.get("events") or [])
    return {
        "version": RETENTION_DELETION_VERSION,
        "package_id": record["package_id"],
        "tenant_id": record["tenant_id"],
        "manifest_sha256": record["manifest_sha256"],
        "retention_until": status.get("retention_until"),
        "legal_hold_active": bool(status.get("legal_hold_active")),
        "retention_expired": bool(status.get("retention_expired")),
        "eligible_for_deletion": bool(status.get("eligible_for_deletion")),
        "lifecycle_event_count": len(events),
        "would_delete": {
            "audit_exports": 1,
            "audit_export_events": len(events),
            "verification_receipts": 0,
        },
        "observed_at": datetime.now(timezone.utc).isoformat(),
    }


def create_signed_deletion_plan(
    *,
    authorization_store: Any,
    lifecycle_store: Any,
    package_id: str,
    operator_id: str,
    signing_key_b64: str,
) -> dict[str, Any]:
    if not signing_key_b64:
        raise RetentionDeletionError("retention deletion planning requires a signing key")
    record = lifecycle_store.get(package_id)
    if record is None:
        raise KeyError(package_id)
    status = lifecycle_store.retention_status(package_id)
    if not status["eligible_for_deletion"]:
        raise RetentionDeletionError("audit export is not eligible for deletion")
    snapshot = build_eligibility_snapshot(record, status)
    signature = sign_receipt(snapshot, signing_key_b64)
    if not signature:
        raise RetentionDeletionError("failed to sign deletion eligibility snapshot")
    return authorization_store.create_plan(
        snapshot=snapshot,
        evidence_signature=signature,
        created_by_operator_id=operator_id,
    )


def _plan_view(plan: Mapping[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    approvals = sorted(
        {
            event["actor_operator_id"]
            for event in events
            if event["event_type"] == "approved"
        }
    )
    cancelled = any(event["event_type"] == "cancelled" for event in events)
    executed = any(event["event_type"] == "executed" for event in events)
    return {
        **dict(plan),
        "approvals": approvals,
        "approval_count": len(approvals),
        "required_approvals": REQUIRED_APPROVALS,
        "cancelled": cancelled,
        "executed": executed,
        "ready_to_execute": len(approvals) >= REQUIRED_APPROVALS and not cancelled and not executed,
        "events": events,
    }


def _validate_execution_plan(plan: Mapping[str, Any], events: list[dict[str, Any]]) -> None:
    view = _plan_view(plan, events)
    if view["cancelled"]:
        raise RetentionDeletionError("deletion plan is cancelled")
    if view["executed"]:
        raise RetentionDeletionError("deletion plan has already executed")
    if view["approval_count"] < REQUIRED_APPROVALS:
        raise RetentionDeletionError("two distinct operator approvals are required")
    signature_result = verify_receipt_signature(
        plan["eligibility_snapshot"],
        plan["evidence_signature"],
    )
    if not signature_result["valid"]:
        raise RetentionDeletionError("deletion eligibility evidence signature is invalid")
    snapshot = plan["eligibility_snapshot"]
    if snapshot.get("package_id") != plan["package_id"]:
        raise RetentionDeletionError("deletion plan package binding is invalid")
    if snapshot.get("tenant_id") != plan["tenant_id"]:
        raise RetentionDeletionError("deletion plan tenant binding is invalid")
    if snapshot.get("manifest_sha256") != plan["manifest_sha256"]:
        raise RetentionDeletionError("deletion plan manifest binding is invalid")
    if not snapshot.get("eligible_for_deletion"):
        raise RetentionDeletionError("signed eligibility snapshot does not permit deletion")


class RetentionDeletionStore:
    """SQLite authorization ledger for local development and tests."""

    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS retention_deletion_plans (
                    plan_id TEXT PRIMARY KEY,
                    package_id TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    manifest_sha256 TEXT NOT NULL,
                    eligibility_snapshot_sha256 TEXT NOT NULL,
                    eligibility_snapshot_json TEXT NOT NULL,
                    evidence_signature_json TEXT NOT NULL,
                    created_by_operator_id TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS retention_deletion_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    plan_id TEXT NOT NULL,
                    actor_operator_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(plan_id) REFERENCES retention_deletion_plans(plan_id)
                )
                """
            )

    def create_plan(self, *, snapshot: Mapping[str, Any], evidence_signature: Mapping[str, Any], created_by_operator_id: str) -> dict[str, Any]:
        snapshot = dict(snapshot)
        snapshot_sha = _sha256(snapshot)
        plan_id = "delete_" + snapshot_sha[:32]
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT plan_id FROM retention_deletion_plans WHERE plan_id = ?",
                (plan_id,),
            ).fetchone()
            if not existing:
                connection.execute(
                    """
                    INSERT INTO retention_deletion_plans (
                        plan_id, package_id, tenant_id, manifest_sha256,
                        eligibility_snapshot_sha256, eligibility_snapshot_json,
                        evidence_signature_json, created_by_operator_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        plan_id,
                        snapshot["package_id"],
                        snapshot["tenant_id"],
                        snapshot["manifest_sha256"],
                        snapshot_sha,
                        _canonical_json(snapshot),
                        _canonical_json(dict(evidence_signature)),
                        created_by_operator_id,
                    ),
                )
        return self.get(plan_id) or {}

    def _events(self, plan_id: str, connection=None) -> list[dict[str, Any]]:
        owns = connection is None
        current = connection or self._connect()
        try:
            rows = current.execute(
                "SELECT event_id, actor_operator_id, event_type, metadata_json, created_at FROM retention_deletion_events WHERE plan_id = ? ORDER BY event_id",
                (plan_id,),
            ).fetchall()
            return [
                {
                    "event_id": row["event_id"],
                    "actor_operator_id": row["actor_operator_id"],
                    "event_type": row["event_type"],
                    "metadata": json.loads(row["metadata_json"]),
                    "created_at": row["created_at"],
                }
                for row in rows
            ]
        finally:
            if owns:
                current.close()

    def get(self, plan_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM retention_deletion_plans WHERE plan_id = ?",
                (plan_id,),
            ).fetchone()
            if row is None:
                return None
            plan = {
                "plan_id": row["plan_id"],
                "package_id": row["package_id"],
                "tenant_id": row["tenant_id"],
                "manifest_sha256": row["manifest_sha256"],
                "eligibility_snapshot_sha256": row["eligibility_snapshot_sha256"],
                "eligibility_snapshot": json.loads(row["eligibility_snapshot_json"]),
                "evidence_signature": json.loads(row["evidence_signature_json"]),
                "created_by_operator_id": row["created_by_operator_id"],
                "created_at": row["created_at"],
            }
            events = self._events(plan_id, connection)
        return _plan_view(plan, events)

    def approve(self, plan_id: str, operator_id: str) -> dict[str, Any]:
        plan = self.get(plan_id)
        if plan is None:
            raise KeyError(plan_id)
        if plan["cancelled"] or plan["executed"]:
            raise RetentionDeletionError("closed deletion plans cannot be approved")
        if operator_id in plan["approvals"]:
            return plan
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO retention_deletion_events (plan_id, actor_operator_id, event_type) VALUES (?, ?, 'approved')",
                (plan_id, operator_id),
            )
        return self.get(plan_id) or {}

    def cancel(self, plan_id: str, operator_id: str, *, reason: str | None = None) -> dict[str, Any]:
        plan = self.get(plan_id)
        if plan is None:
            raise KeyError(plan_id)
        if plan["executed"]:
            raise RetentionDeletionError("executed deletion plans cannot be cancelled")
        if plan["cancelled"]:
            return plan
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO retention_deletion_events (plan_id, actor_operator_id, event_type, metadata_json) VALUES (?, ?, 'cancelled', ?)",
                (plan_id, operator_id, _canonical_json({"reason": reason})),
            )
        return self.get(plan_id) or {}

    def execute(self, plan_id: str, operator_id: str, *, now: datetime | None = None) -> dict[str, Any]:
        now = now or datetime.now(timezone.utc)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM retention_deletion_plans WHERE plan_id = ?",
                (plan_id,),
            ).fetchone()
            if row is None:
                raise KeyError(plan_id)
            plan = {
                "plan_id": row["plan_id"],
                "package_id": row["package_id"],
                "tenant_id": row["tenant_id"],
                "manifest_sha256": row["manifest_sha256"],
                "eligibility_snapshot": json.loads(row["eligibility_snapshot_json"]),
                "evidence_signature": json.loads(row["evidence_signature_json"]),
            }
            events = self._events(plan_id, connection)
            _validate_execution_plan(plan, events)

            export = connection.execute(
                "SELECT tenant_id, manifest_sha256, retention_until FROM audit_exports WHERE package_id = ?",
                (plan["package_id"],),
            ).fetchone()
            if export is None:
                raise RetentionDeletionError("audit export no longer exists")
            if export["tenant_id"] != plan["tenant_id"] or export["manifest_sha256"] != plan["manifest_sha256"]:
                raise RetentionDeletionError("audit export changed after deletion planning")
            lifecycle = connection.execute(
                "SELECT event_type FROM audit_export_events WHERE package_id = ? ORDER BY event_id",
                (plan["package_id"],),
            ).fetchall()
            hold = False
            for event in lifecycle:
                if event["event_type"] == "legal_hold_placed":
                    hold = True
                elif event["event_type"] == "legal_hold_released":
                    hold = False
            retention_until = _parse_time(export["retention_until"])
            if retention_until is None or now < retention_until or hold:
                raise RetentionDeletionError("audit export is no longer eligible for deletion")

            deleted_events = connection.execute(
                "DELETE FROM audit_export_events WHERE package_id = ?",
                (plan["package_id"],),
            ).rowcount
            deleted_export = connection.execute(
                "DELETE FROM audit_exports WHERE package_id = ?",
                (plan["package_id"],),
            ).rowcount
            connection.execute(
                "INSERT INTO retention_deletion_events (plan_id, actor_operator_id, event_type, metadata_json) VALUES (?, ?, 'executed', ?)",
                (
                    plan_id,
                    operator_id,
                    _canonical_json(
                        {
                            "deleted_audit_exports": deleted_export,
                            "deleted_audit_export_events": deleted_events,
                            "deleted_verification_receipts": 0,
                        }
                    ),
                ),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return self.get(plan_id) or {}


class NeonRetentionDeletionStore:
    """Operator-role retention authorization and atomic deletion for Neon."""

    def __init__(self, backend):
        self.backend = backend

    def create_plan(self, *, snapshot: Mapping[str, Any], evidence_signature: Mapping[str, Any], created_by_operator_id: str) -> dict[str, Any]:
        snapshot = dict(snapshot)
        snapshot_sha = _sha256(snapshot)
        plan_id = "delete_" + snapshot_sha[:32]
        with self.backend.connect() as connection:
            connection.execute(
                """
                INSERT INTO retention_deletion_plans (
                    plan_id, package_id, tenant_id, manifest_sha256,
                    eligibility_snapshot_sha256, eligibility_snapshot_json,
                    evidence_signature_json, created_by_operator_id
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (plan_id) DO NOTHING
                """,
                (
                    plan_id,
                    snapshot["package_id"],
                    snapshot["tenant_id"],
                    snapshot["manifest_sha256"],
                    snapshot_sha,
                    _canonical_json(snapshot),
                    _canonical_json(dict(evidence_signature)),
                    created_by_operator_id,
                ),
            )
        return self.get(plan_id) or {}

    def _events(self, connection, plan_id: str) -> list[dict[str, Any]]:
        rows = connection.execute(
            "SELECT event_id, actor_operator_id, event_type, metadata_json, created_at FROM retention_deletion_events WHERE plan_id=%s ORDER BY event_id",
            (plan_id,),
        ).fetchall()
        return [
            {
                "event_id": row["event_id"],
                "actor_operator_id": row["actor_operator_id"],
                "event_type": row["event_type"],
                "metadata": json.loads(row["metadata_json"]),
                "created_at": row["created_at"].isoformat() if hasattr(row["created_at"], "isoformat") else str(row["created_at"]),
            }
            for row in rows
        ]

    def get(self, plan_id: str) -> dict[str, Any] | None:
        with self.backend.connect() as connection:
            row = connection.execute(
                "SELECT * FROM retention_deletion_plans WHERE plan_id=%s",
                (plan_id,),
            ).fetchone()
            if row is None:
                return None
            plan = {
                "plan_id": row["plan_id"],
                "package_id": row["package_id"],
                "tenant_id": row["tenant_id"],
                "manifest_sha256": row["manifest_sha256"],
                "eligibility_snapshot_sha256": row["eligibility_snapshot_sha256"],
                "eligibility_snapshot": json.loads(row["eligibility_snapshot_json"]),
                "evidence_signature": json.loads(row["evidence_signature_json"]),
                "created_by_operator_id": row["created_by_operator_id"],
                "created_at": row["created_at"].isoformat() if hasattr(row["created_at"], "isoformat") else str(row["created_at"]),
            }
            events = self._events(connection, plan_id)
        return _plan_view(plan, events)

    def approve(self, plan_id: str, operator_id: str) -> dict[str, Any]:
        plan = self.get(plan_id)
        if plan is None:
            raise KeyError(plan_id)
        if plan["cancelled"] or plan["executed"]:
            raise RetentionDeletionError("closed deletion plans cannot be approved")
        with self.backend.connect() as connection:
            connection.execute(
                """
                INSERT INTO retention_deletion_events (plan_id, actor_operator_id, event_type)
                VALUES (%s, %s, 'approved')
                ON CONFLICT DO NOTHING
                """,
                (plan_id, operator_id),
            )
        return self.get(plan_id) or {}

    def cancel(self, plan_id: str, operator_id: str, *, reason: str | None = None) -> dict[str, Any]:
        plan = self.get(plan_id)
        if plan is None:
            raise KeyError(plan_id)
        if plan["executed"]:
            raise RetentionDeletionError("executed deletion plans cannot be cancelled")
        if plan["cancelled"]:
            return plan
        with self.backend.connect() as connection:
            connection.execute(
                "INSERT INTO retention_deletion_events (plan_id, actor_operator_id, event_type, metadata_json) VALUES (%s, %s, 'cancelled', %s)",
                (plan_id, operator_id, _canonical_json({"reason": reason})),
            )
        return self.get(plan_id) or {}

    def execute(self, plan_id: str, operator_id: str, *, now: datetime | None = None) -> dict[str, Any]:
        now = now or datetime.now(timezone.utc)
        with self.backend.connect() as connection:
            row = connection.execute(
                "SELECT * FROM retention_deletion_plans WHERE plan_id=%s FOR UPDATE",
                (plan_id,),
            ).fetchone()
            if row is None:
                raise KeyError(plan_id)
            plan = {
                "plan_id": row["plan_id"],
                "package_id": row["package_id"],
                "tenant_id": row["tenant_id"],
                "manifest_sha256": row["manifest_sha256"],
                "eligibility_snapshot": json.loads(row["eligibility_snapshot_json"]),
                "evidence_signature": json.loads(row["evidence_signature_json"]),
            }
            events = self._events(connection, plan_id)
            _validate_execution_plan(plan, events)

            export = connection.execute(
                "SELECT tenant_id, manifest_sha256, retention_until FROM audit_exports WHERE package_id=%s FOR UPDATE",
                (plan["package_id"],),
            ).fetchone()
            if export is None:
                raise RetentionDeletionError("audit export no longer exists")
            if export["tenant_id"] != plan["tenant_id"] or export["manifest_sha256"] != plan["manifest_sha256"]:
                raise RetentionDeletionError("audit export changed after deletion planning")
            lifecycle = connection.execute(
                "SELECT event_type FROM audit_export_events WHERE package_id=%s ORDER BY event_id FOR UPDATE",
                (plan["package_id"],),
            ).fetchall()
            hold = False
            for event in lifecycle:
                if event["event_type"] == "legal_hold_placed":
                    hold = True
                elif event["event_type"] == "legal_hold_released":
                    hold = False
            retention_until = _parse_time(export["retention_until"])
            if retention_until is None or now < retention_until or hold:
                raise RetentionDeletionError("audit export is no longer eligible for deletion")

            deleted_events = connection.execute(
                "DELETE FROM audit_export_events WHERE package_id=%s",
                (plan["package_id"],),
            ).rowcount
            deleted_export = connection.execute(
                "DELETE FROM audit_exports WHERE package_id=%s",
                (plan["package_id"],),
            ).rowcount
            connection.execute(
                "INSERT INTO retention_deletion_events (plan_id, actor_operator_id, event_type, metadata_json) VALUES (%s, %s, 'executed', %s)",
                (
                    plan_id,
                    operator_id,
                    _canonical_json(
                        {
                            "deleted_audit_exports": deleted_export,
                            "deleted_audit_export_events": deleted_events,
                            "deleted_verification_receipts": 0,
                        }
                    ),
                ),
            )
        return self.get(plan_id) or {}
