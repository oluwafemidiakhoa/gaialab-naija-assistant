"""Immutable per-tenant policy packs for GaiaLab Naija Trust Rail.

Tenant policies can only make a verification result stricter. They never replace
or downgrade the global deterministic Trust Engine disposition.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Mapping
import uuid

POLICY_PACK_VERSION = "gaialab-naija-tenant-policy/0.1.0"

DEFAULT_POLICY: dict[str, Any] = {
    "name": "gaialab-default",
    "max_automated_risk": 100,
    "require_human_review_above_ngn": None,
    "block_finding_codes": [],
    "escalate_finding_codes": [],
    "require_signed_receipts": False,
    "require_persisted_receipts": False,
}

_ALLOWED_FIELDS = frozenset(DEFAULT_POLICY)
_DISPOSITION_RANK = {"ALLOW": 0, "VERIFY": 1, "REWRITE": 2, "ESCALATE": 3, "BLOCK": 4}


class TenantPolicyError(RuntimeError):
    """Raised when policy-pack lifecycle or validation rules are violated."""


class TenantPolicyConfigurationError(TenantPolicyError):
    """Raised when a tenant policy requires unavailable runtime infrastructure."""


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _policy_hash(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _normalize_codes(value: Any, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"{field} must be a list of non-empty strings")
    return sorted(set(item.strip().upper() for item in value))


def normalize_policy(policy: Mapping[str, Any] | None) -> dict[str, Any]:
    supplied = dict(policy or {})
    unknown = sorted(set(supplied) - _ALLOWED_FIELDS)
    if unknown:
        raise ValueError(f"unknown tenant policy fields: {', '.join(unknown)}")

    normalized = {**DEFAULT_POLICY, **supplied}
    name = str(normalized["name"]).strip()
    if not name:
        raise ValueError("policy name must not be empty")
    normalized["name"] = name

    risk = normalized["max_automated_risk"]
    if not isinstance(risk, int) or isinstance(risk, bool) or not 0 <= risk <= 100:
        raise ValueError("max_automated_risk must be an integer from 0 to 100")

    threshold = normalized["require_human_review_above_ngn"]
    if threshold is not None:
        try:
            threshold_decimal = Decimal(str(threshold).replace(",", ""))
        except InvalidOperation as exc:
            raise ValueError("require_human_review_above_ngn must be numeric or null") from exc
        if threshold_decimal < 0:
            raise ValueError("require_human_review_above_ngn must be non-negative")
        normalized["require_human_review_above_ngn"] = str(threshold_decimal.normalize())

    normalized["block_finding_codes"] = _normalize_codes(
        normalized["block_finding_codes"], "block_finding_codes"
    )
    normalized["escalate_finding_codes"] = _normalize_codes(
        normalized["escalate_finding_codes"], "escalate_finding_codes"
    )

    overlap = set(normalized["block_finding_codes"]) & set(normalized["escalate_finding_codes"])
    if overlap:
        raise ValueError(f"finding codes cannot be both block and escalate: {', '.join(sorted(overlap))}")

    for field in ("require_signed_receipts", "require_persisted_receipts"):
        if not isinstance(normalized[field], bool):
            raise ValueError(f"{field} must be a boolean")

    return normalized


def default_policy_record(tenant_id: str | None = None) -> dict[str, Any]:
    policy = normalize_policy(DEFAULT_POLICY)
    core = {"version": POLICY_PACK_VERSION, "tenant_id": tenant_id, "policy": policy}
    return {
        "policy_id": "policy_default",
        "policy_hash": _policy_hash(core),
        "tenant_id": tenant_id,
        "policy": policy,
        "status": "default",
        "created_at": None,
    }


class TenantPolicyStore:
    """SQLite store for immutable policy versions and append-only activation events."""

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
                CREATE TABLE IF NOT EXISTS tenant_policy_versions (
                    policy_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    policy_hash TEXT NOT NULL,
                    policy_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(tenant_id, policy_hash)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS tenant_policy_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant_id TEXT NOT NULL,
                    policy_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(policy_id) REFERENCES tenant_policy_versions(policy_id)
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_tenant_policy_events ON tenant_policy_events(tenant_id, event_id)"
            )

    def create_version(
        self,
        tenant_id: str,
        policy: Mapping[str, Any],
        *,
        activate: bool = True,
        note: str | None = None,
    ) -> dict[str, Any]:
        if not tenant_id.strip():
            raise ValueError("tenant_id must not be empty")
        normalized = normalize_policy(policy)
        policy_json = _canonical_json(normalized)
        digest = hashlib.sha256(policy_json.encode("utf-8")).hexdigest()
        with self._connect() as connection:
            existing = connection.execute(
                """
                SELECT policy_id FROM tenant_policy_versions
                WHERE tenant_id = ? AND policy_hash = ?
                """,
                (tenant_id, digest),
            ).fetchone()
            if existing:
                policy_id = existing["policy_id"]
            else:
                policy_id = f"policy_{uuid.uuid4().hex[:20]}"
                connection.execute(
                    """
                    INSERT INTO tenant_policy_versions (policy_id, tenant_id, policy_hash, policy_json)
                    VALUES (?, ?, ?, ?)
                    """,
                    (policy_id, tenant_id, digest, policy_json),
                )
                connection.execute(
                    """
                    INSERT INTO tenant_policy_events (tenant_id, policy_id, event_type, metadata_json)
                    VALUES (?, ?, 'created', ?)
                    """,
                    (tenant_id, policy_id, _canonical_json({"note": note})),
                )
            if activate:
                connection.execute(
                    """
                    INSERT INTO tenant_policy_events (tenant_id, policy_id, event_type, metadata_json)
                    VALUES (?, ?, 'activated', ?)
                    """,
                    (tenant_id, policy_id, _canonical_json({"note": note})),
                )
        record = self.get(policy_id)
        if record is None:  # pragma: no cover
            raise TenantPolicyError("policy version could not be read back")
        return record

    def activate(self, tenant_id: str, policy_id: str, *, note: str | None = None) -> dict[str, Any]:
        record = self.get(policy_id)
        if record is None or record["tenant_id"] != tenant_id:
            raise KeyError(policy_id)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO tenant_policy_events (tenant_id, policy_id, event_type, metadata_json)
                VALUES (?, ?, 'activated', ?)
                """,
                (tenant_id, policy_id, _canonical_json({"note": note})),
            )
        return self.get(policy_id) or record

    def get(self, policy_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT policy_id, tenant_id, policy_hash, policy_json, created_at
                FROM tenant_policy_versions
                WHERE policy_id = ?
                """,
                (policy_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "policy_id": row["policy_id"],
            "tenant_id": row["tenant_id"],
            "policy_hash": row["policy_hash"],
            "policy": json.loads(row["policy_json"]),
            "created_at": row["created_at"],
        }

    def active_for(self, tenant_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT policy_id
                FROM tenant_policy_events
                WHERE tenant_id = ? AND event_type = 'activated'
                ORDER BY event_id DESC
                LIMIT 1
                """,
                (tenant_id,),
            ).fetchone()
        if row is None:
            return default_policy_record(tenant_id)
        return self.get(row["policy_id"]) or default_policy_record(tenant_id)

    def list_versions(self, tenant_id: str) -> list[dict[str, Any]]:
        active = self.active_for(tenant_id)["policy_id"]
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT policy_id FROM tenant_policy_versions
                WHERE tenant_id = ? ORDER BY created_at ASC, policy_id ASC
                """,
                (tenant_id,),
            ).fetchall()
        records: list[dict[str, Any]] = []
        for row in rows:
            record = self.get(row["policy_id"])
            if record:
                records.append({**record, "active": record["policy_id"] == active})
        return records


def _money(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    text = str(value).upper().replace("NGN", "").replace("₦", "").replace(",", "").strip()
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def _largest_amount(
    claims: Mapping[str, Any],
    authoritative_state: Mapping[str, Any],
    evidence: Mapping[str, Any],
) -> Decimal | None:
    values: list[Decimal] = []
    for source in (claims, authoritative_state, evidence):
        for key in ("amount", "transaction_amount"):
            parsed = _money(source.get(key))
            if parsed is not None:
                values.append(parsed)
    return max(values) if values else None


def evaluate_tenant_policy(
    policy_record: Mapping[str, Any] | None,
    *,
    base_disposition: str,
    risk_score: int,
    findings: list[Mapping[str, Any]],
    claims: Mapping[str, Any],
    authoritative_state: Mapping[str, Any],
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    record = dict(policy_record or default_policy_record())
    policy = normalize_policy(record.get("policy") or {})
    required = "ALLOW"
    reasons: list[dict[str, Any]] = []
    finding_codes = {str(item.get("code", "")).upper() for item in findings}

    blocked = sorted(finding_codes & set(policy["block_finding_codes"]))
    if blocked:
        required = "BLOCK"
        reasons.append({"code": "TENANT_BLOCK_FINDING", "finding_codes": blocked})

    escalated = sorted(finding_codes & set(policy["escalate_finding_codes"]))
    if escalated and _DISPOSITION_RANK[required] < _DISPOSITION_RANK["ESCALATE"]:
        required = "ESCALATE"
        reasons.append({"code": "TENANT_ESCALATE_FINDING", "finding_codes": escalated})

    if risk_score > policy["max_automated_risk"] and _DISPOSITION_RANK[required] < _DISPOSITION_RANK["ESCALATE"]:
        required = "ESCALATE"
        reasons.append(
            {
                "code": "TENANT_RISK_THRESHOLD",
                "risk_score": risk_score,
                "max_automated_risk": policy["max_automated_risk"],
            }
        )

    amount = _largest_amount(claims, authoritative_state, evidence)
    threshold = _money(policy["require_human_review_above_ngn"])
    if amount is not None and threshold is not None and amount > threshold:
        if _DISPOSITION_RANK[required] < _DISPOSITION_RANK["ESCALATE"]:
            required = "ESCALATE"
        reasons.append(
            {
                "code": "TENANT_HIGH_VALUE_REVIEW",
                "amount_ngn": str(amount),
                "threshold_ngn": str(threshold),
            }
        )

    final_disposition = (
        base_disposition
        if _DISPOSITION_RANK[base_disposition] >= _DISPOSITION_RANK[required]
        else required
    )
    core = {
        "policy_id": record.get("policy_id", "policy_default"),
        "policy_hash": record.get("policy_hash"),
        "base_disposition": base_disposition,
        "required_disposition": required,
        "final_disposition": final_disposition,
        "reasons": reasons,
    }
    return {
        "evaluation_id": _policy_hash(core),
        **core,
        "policy_name": policy["name"],
        "runtime_requirements": {
            "signed_receipts": policy["require_signed_receipts"],
            "persisted_receipts": policy["require_persisted_receipts"],
        },
    }


def enforce_runtime_requirements(
    policy_record: Mapping[str, Any],
    *,
    signing_configured: bool,
    persistence_configured: bool,
) -> None:
    policy = normalize_policy(policy_record.get("policy") or {})
    if policy["require_signed_receipts"] and not signing_configured:
        raise TenantPolicyConfigurationError("tenant policy requires signed receipts")
    if policy["require_persisted_receipts"] and not persistence_configured:
        raise TenantPolicyConfigurationError("tenant policy requires persisted receipts")
