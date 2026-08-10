"""Read-only data aggregation for the GaiaLab Naija Trust Dashboard.

This module performs SELECT-only queries against Trust Rail storage. It never
mutates receipts, audit lifecycle, retention state, operator actions, policies,
keys, governed datasets, or publication/training state.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
import os
import sqlite3
from typing import Any

from src.operator_auth import require_admin_scope
from src.storage_backend import operator_action_log, operator_neon_backend, operator_registry

DASHBOARD_VERSION = "gaialab-naija-trust-dashboard/0.1.0"
MAX_DASHBOARD_ROWS = 2000


def authenticate_dashboard_operator(admin_api_key: str) -> dict[str, Any]:
    identity = operator_registry().authenticate(admin_api_key)
    if identity is None:
        raise PermissionError("invalid or disabled admin API key")
    require_admin_scope(identity, "dashboard:read")
    return identity


def _parse_receipt(row: Any) -> dict[str, Any]:
    envelope = json.loads(row["payload_json"])
    receipt = dict(envelope.get("verification_receipt") or {})
    return {
        "verification_id": row["verification_id"],
        "created_at": str(row["created_at"]),
        "payload_sha256": row["payload_sha256"],
        "tenant_id": row["tenant_id"],
        "model_name": receipt.get("model_name") or "unknown",
        "model_version": receipt.get("model_version"),
        "language": receipt.get("language"),
        "disposition": receipt.get("disposition") or "UNKNOWN",
        "risk_score": int(receipt.get("risk_score") or 0),
        "finding_codes": list(receipt.get("finding_codes") or []),
        "tenant_policy_id": receipt.get("tenant_policy_id"),
        "signed": bool(envelope.get("signature")),
    }


def _sqlite_receipts(tenant_id: str, limit: int) -> list[dict[str, Any]]:
    path = os.getenv("GAIALAB_TRUST_RECEIPT_DB")
    if not path:
        raise RuntimeError("receipt persistence is not configured")
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            """
            SELECT verification_id, payload_sha256, payload_json, tenant_id, created_at
            FROM verification_receipts
            WHERE tenant_id = ?
            ORDER BY created_at DESC, verification_id DESC
            LIMIT ?
            """,
            (tenant_id, limit),
        ).fetchall()
    finally:
        connection.close()
    return [_parse_receipt(row) for row in rows]


def _neon_receipts(tenant_id: str, limit: int) -> list[dict[str, Any]]:
    backend = operator_neon_backend()
    if backend is None:
        raise RuntimeError("Neon operator runtime is not configured")
    with backend.connect() as connection:
        rows = connection.execute(
            """
            SELECT verification_id, payload_sha256, payload_json, tenant_id, created_at
            FROM verification_receipts
            WHERE tenant_id = %s
            ORDER BY created_at DESC, verification_id DESC
            LIMIT %s
            """,
            (tenant_id, limit),
        ).fetchall()
    return [_parse_receipt(row) for row in rows]


def list_receipts(tenant_id: str, *, limit: int = 500) -> list[dict[str, Any]]:
    if not tenant_id:
        raise ValueError("tenant_id must not be empty")
    if not 1 <= limit <= MAX_DASHBOARD_ROWS:
        raise ValueError(f"limit must be between 1 and {MAX_DASHBOARD_ROWS}")
    if os.getenv("GAIALAB_DATABASE_URL"):
        return _neon_receipts(tenant_id, limit)
    return _sqlite_receipts(tenant_id, limit)


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _retention_flags(retention_until: str | None, legal_hold_active: bool) -> tuple[bool, bool]:
    expired = False
    if retention_until:
        parsed = datetime.fromisoformat(str(retention_until).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        expired = datetime.now(timezone.utc) >= parsed
    return expired, bool(expired and not legal_hold_active)


def _sqlite_exports(tenant_id: str, limit: int) -> list[dict[str, Any]]:
    path = os.getenv("GAIALAB_AUDIT_LIFECYCLE_DB")
    if not path:
        return []
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            """
            SELECT package_id, tenant_id, manifest_sha256, retention_until, created_at
            FROM audit_exports
            WHERE tenant_id = ?
            ORDER BY created_at DESC, package_id DESC
            LIMIT ?
            """,
            (tenant_id, limit),
        ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            events = connection.execute(
                "SELECT event_type FROM audit_export_events WHERE package_id = ? ORDER BY event_id",
                (row["package_id"],),
            ).fetchall()
            hold = False
            for event in events:
                if event["event_type"] == "legal_hold_placed":
                    hold = True
                elif event["event_type"] == "legal_hold_released":
                    hold = False
            expired, eligible = _retention_flags(row["retention_until"], hold)
            result.append(
                {
                    "package_id": row["package_id"],
                    "tenant_id": row["tenant_id"],
                    "manifest_sha256": row["manifest_sha256"],
                    "retention_until": row["retention_until"],
                    "created_at": row["created_at"],
                    "legal_hold_active": hold,
                    "retention_expired": expired,
                    "eligible_for_deletion": eligible,
                }
            )
        return result
    finally:
        connection.close()


def _neon_exports(tenant_id: str, limit: int) -> list[dict[str, Any]]:
    backend = operator_neon_backend()
    if backend is None:
        return []
    with backend.connect() as connection:
        rows = connection.execute(
            """
            SELECT package_id, tenant_id, manifest_sha256, retention_until, created_at
            FROM audit_exports
            WHERE tenant_id = %s
            ORDER BY created_at DESC, package_id DESC
            LIMIT %s
            """,
            (tenant_id, limit),
        ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            events = connection.execute(
                "SELECT event_type FROM audit_export_events WHERE package_id = %s ORDER BY event_id",
                (row["package_id"],),
            ).fetchall()
            hold = False
            for event in events:
                if event["event_type"] == "legal_hold_placed":
                    hold = True
                elif event["event_type"] == "legal_hold_released":
                    hold = False
            retention_until = _iso(row["retention_until"])
            expired, eligible = _retention_flags(retention_until, hold)
            result.append(
                {
                    "package_id": row["package_id"],
                    "tenant_id": row["tenant_id"],
                    "manifest_sha256": row["manifest_sha256"],
                    "retention_until": retention_until,
                    "created_at": _iso(row["created_at"]),
                    "legal_hold_active": hold,
                    "retention_expired": expired,
                    "eligible_for_deletion": eligible,
                }
            )
        return result


def list_audit_exports(tenant_id: str, *, limit: int = 500) -> list[dict[str, Any]]:
    if not 1 <= limit <= MAX_DASHBOARD_ROWS:
        raise ValueError(f"limit must be between 1 and {MAX_DASHBOARD_ROWS}")
    return _neon_exports(tenant_id, limit) if os.getenv("GAIALAB_DATABASE_URL") else _sqlite_exports(tenant_id, limit)


def _provider_bucket(model_name: str) -> str:
    lowered = model_name.lower()
    for provider in ("openai", "anthropic", "gemini", "google", "qwen", "n-atlas", "natlas", "local", "private"):
        if lowered.startswith(provider + "/") or provider in lowered:
            return "gemini" if provider == "google" else provider
    return "custom"


def tenant_snapshot(tenant_id: str, *, limit: int = 500) -> dict[str, Any]:
    receipts = list_receipts(tenant_id, limit=limit)
    exports = list_audit_exports(tenant_id, limit=limit)
    dispositions = Counter(item["disposition"] for item in receipts)
    models = Counter(item["model_name"] for item in receipts)
    providers = Counter(_provider_bucket(item["model_name"]) for item in receipts)
    languages = Counter(item["language"] or "unspecified" for item in receipts)
    findings: Counter[str] = Counter()
    model_risk: dict[str, list[int]] = defaultdict(list)
    for item in receipts:
        findings.update(item["finding_codes"])
        model_risk[item["model_name"]].append(item["risk_score"])
    risk_values = [item["risk_score"] for item in receipts]
    return {
        "version": DASHBOARD_VERSION,
        "tenant_id": tenant_id,
        "receipt_count": len(receipts),
        "average_risk_score": round(sum(risk_values) / len(risk_values), 2) if risk_values else 0.0,
        "high_risk_count": sum(score >= 70 for score in risk_values),
        "dispositions": dict(dispositions),
        "models": dict(models),
        "providers": dict(providers),
        "languages": dict(languages),
        "finding_codes": dict(findings),
        "model_average_risk": {
            model: round(sum(values) / len(values), 2) for model, values in sorted(model_risk.items())
        },
        "audit_export_count": len(exports),
        "legal_hold_count": sum(item["legal_hold_active"] for item in exports),
        "retention_eligible_count": sum(item["eligible_for_deletion"] for item in exports),
        "receipts": receipts,
        "audit_exports": exports,
    }


def operator_chain_snapshot(*, action_limit: int = 200) -> dict[str, Any]:
    log = operator_action_log(required=False)
    if log is None:
        return {"configured": False, "valid": None, "reason": "operator_action_log_not_configured", "actions": []}
    verification = log.verify_chain()
    actions = log.list(limit=action_limit)
    return {"configured": True, **verification, "actions": list(reversed(actions))}
