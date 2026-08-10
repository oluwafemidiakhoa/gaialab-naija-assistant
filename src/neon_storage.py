"""Neon Postgres storage backend for GaiaLab Naija Trust Rail.

Runtime traffic should use a pooled Neon connection string. Schema initialization
should use a direct connection string when available.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import time
from typing import Any, Iterable, Mapping
import uuid

import psycopg
from psycopg.rows import dict_row

from src.audit_lifecycle import AuditLifecycleError
from src.key_registry import SigningKeyRegistryError, signing_key_id
from src.operator_auth import ADMIN_KEY_PREFIX, OperatorAuthError, _normalize_scopes as _normalize_admin_scopes
from src.rate_limit import RateLimitDecision
from src.receipt_store import ReceiptConflictError, _canonical_json as _receipt_json
from src.tenant_auth import API_KEY_PREFIX, TenantAuthError, _normalize_scopes as _normalize_tenant_scopes
from src.tenant_policy import TenantPolicyError, default_policy_record, normalize_policy


SCHEMA_VERSION = "gaialab-naija-neon/0.1.0"


def _json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _sha256(payload: Any) -> str:
    return hashlib.sha256(_json(payload).encode("utf-8")).hexdigest()


def _hash_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def _iso(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    return value


class NeonBackend:
    """Shared Neon connection and schema owner."""

    def __init__(self, database_url: str, migration_database_url: str | None = None):
        if not database_url.startswith(("postgresql://", "postgres://")):
            raise ValueError("Neon database URL must use postgresql:// or postgres://")
        self.database_url = database_url
        self.migration_database_url = migration_database_url or database_url
        self.initialize()

    def connect(self):
        return psycopg.connect(self.database_url, row_factory=dict_row)

    def migration_connect(self):
        return psycopg.connect(self.migration_database_url, row_factory=dict_row)

    def initialize(self) -> None:
        statements = [
            """
            CREATE TABLE IF NOT EXISTS tenants (
                tenant_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS tenant_api_keys (
                key_id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL REFERENCES tenants(tenant_id),
                key_hash TEXT NOT NULL UNIQUE,
                label TEXT,
                scopes_json TEXT NOT NULL,
                rate_limit_per_minute INTEGER NOT NULL DEFAULT 120,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                disabled_at TIMESTAMPTZ
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_tenant_api_keys_tenant ON tenant_api_keys(tenant_id, status)",
            """
            CREATE TABLE IF NOT EXISTS operators (
                operator_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS operator_api_keys (
                key_id TEXT PRIMARY KEY,
                operator_id TEXT NOT NULL REFERENCES operators(operator_id),
                key_hash TEXT NOT NULL UNIQUE,
                label TEXT,
                scopes_json TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                disabled_at TIMESTAMPTZ
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_operator_keys_operator ON operator_api_keys(operator_id, status)",
            """
            CREATE TABLE IF NOT EXISTS signing_keys (
                key_id TEXT PRIMARY KEY,
                public_key_b64 TEXT NOT NULL,
                algorithm TEXT NOT NULL,
                label TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS signing_key_events (
                event_id BIGSERIAL PRIMARY KEY,
                key_id TEXT NOT NULL REFERENCES signing_keys(key_id),
                event_type TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_signing_key_events_key ON signing_key_events(key_id, event_id)",
            """
            CREATE TABLE IF NOT EXISTS tenant_policy_versions (
                policy_id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                policy_hash TEXT NOT NULL,
                policy_json TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(tenant_id, policy_hash)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS tenant_policy_events (
                event_id BIGSERIAL PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                policy_id TEXT NOT NULL REFERENCES tenant_policy_versions(policy_id),
                event_type TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_tenant_policy_events ON tenant_policy_events(tenant_id, event_id)",
            """
            CREATE TABLE IF NOT EXISTS verification_receipts (
                verification_id TEXT PRIMARY KEY,
                payload_sha256 TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                tenant_id TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_verification_receipts_tenant ON verification_receipts(tenant_id, created_at)",
            """
            CREATE TABLE IF NOT EXISTS api_rate_windows (
                key_id TEXT NOT NULL,
                bucket_start BIGINT NOT NULL,
                count INTEGER NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(key_id, bucket_start)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS audit_exports (
                package_id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                manifest_sha256 TEXT NOT NULL,
                manifest_json TEXT NOT NULL,
                retention_until TIMESTAMPTZ,
                created_by_key_id TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS audit_export_events (
                event_id BIGSERIAL PRIMARY KEY,
                package_id TEXT NOT NULL REFERENCES audit_exports(package_id),
                actor_type TEXT NOT NULL,
                actor_id TEXT,
                event_type TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_audit_export_events ON audit_export_events(package_id, event_id)",
            "CREATE INDEX IF NOT EXISTS idx_audit_exports_tenant ON audit_exports(tenant_id, created_at)",
        ]
        with self.migration_connect() as connection:
            with connection.cursor() as cursor:
                for statement in statements:
                    cursor.execute(statement)


class NeonTenantRegistry:
    def __init__(self, backend: NeonBackend):
        self.backend = backend

    def create_tenant(self, name: str, tenant_id: str | None = None) -> dict[str, Any]:
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("tenant name must not be empty")
        tenant_id = tenant_id or f"tenant_{uuid.uuid4().hex[:16]}"
        with self.backend.connect() as connection:
            connection.execute(
                "INSERT INTO tenants (tenant_id, name) VALUES (%s, %s)",
                (tenant_id, clean_name),
            )
        record = self.get_tenant(tenant_id)
        if record is None:
            raise TenantAuthError("created tenant could not be read back")
        return record

    def get_tenant(self, tenant_id: str) -> dict[str, Any] | None:
        with self.backend.connect() as connection:
            row = connection.execute(
                "SELECT tenant_id, name, status, created_at FROM tenants WHERE tenant_id = %s",
                (tenant_id,),
            ).fetchone()
        if row is None:
            return None
        return {**row, "created_at": _iso(row["created_at"])}

    def issue_api_key(
        self,
        tenant_id: str,
        *,
        label: str | None = None,
        scopes: Iterable[str] | None = None,
        rate_limit_per_minute: int = 120,
    ) -> dict[str, Any]:
        import secrets

        tenant = self.get_tenant(tenant_id)
        if tenant is None or tenant["status"] != "active":
            raise TenantAuthError("tenant is missing or inactive")
        normalized_scopes = _normalize_tenant_scopes(scopes)
        if not isinstance(rate_limit_per_minute, int) or isinstance(rate_limit_per_minute, bool) or rate_limit_per_minute <= 0:
            raise ValueError("rate_limit_per_minute must be a positive integer")
        api_key = API_KEY_PREFIX + secrets.token_urlsafe(32)
        digest = _hash_key(api_key)
        key_id = "gk_" + digest[:20]
        with self.backend.connect() as connection:
            connection.execute(
                """
                INSERT INTO tenant_api_keys
                    (key_id, tenant_id, key_hash, label, scopes_json, rate_limit_per_minute)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (key_id, tenant_id, digest, label, json.dumps(normalized_scopes), rate_limit_per_minute),
            )
        return {
            "api_key": api_key,
            "key_id": key_id,
            "tenant_id": tenant_id,
            "scopes": list(normalized_scopes),
            "rate_limit_per_minute": rate_limit_per_minute,
        }

    def authenticate(self, api_key: str) -> dict[str, Any] | None:
        if not api_key or not api_key.startswith(API_KEY_PREFIX):
            return None
        with self.backend.connect() as connection:
            row = connection.execute(
                """
                SELECT k.key_id, k.tenant_id, k.label, k.scopes_json,
                       k.rate_limit_per_minute, t.name AS tenant_name
                FROM tenant_api_keys AS k
                JOIN tenants AS t ON t.tenant_id = k.tenant_id
                WHERE k.key_hash = %s AND k.status = 'active' AND t.status = 'active'
                """,
                (_hash_key(api_key),),
            ).fetchone()
        if row is None:
            return None
        identity = dict(row)
        identity["scopes"] = json.loads(identity.pop("scopes_json"))
        return identity

    def disable_api_key(self, key_id: str) -> None:
        with self.backend.connect() as connection:
            row = connection.execute(
                """
                UPDATE tenant_api_keys
                SET status = 'disabled', disabled_at = CURRENT_TIMESTAMP
                WHERE key_id = %s AND status = 'active'
                RETURNING key_id
                """,
                (key_id,),
            ).fetchone()
        if row is None:
            raise KeyError(key_id)


class NeonOperatorRegistry:
    def __init__(self, backend: NeonBackend):
        self.backend = backend

    def create_operator(self, name: str, operator_id: str | None = None) -> dict[str, Any]:
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("operator name must not be empty")
        operator_id = operator_id or f"operator_{uuid.uuid4().hex[:16]}"
        with self.backend.connect() as connection:
            connection.execute(
                "INSERT INTO operators (operator_id, name) VALUES (%s, %s)",
                (operator_id, clean_name),
            )
        record = self.get_operator(operator_id)
        if record is None:
            raise OperatorAuthError("created operator could not be read back")
        return record

    def get_operator(self, operator_id: str) -> dict[str, Any] | None:
        with self.backend.connect() as connection:
            row = connection.execute(
                "SELECT operator_id, name, status, created_at FROM operators WHERE operator_id = %s",
                (operator_id,),
            ).fetchone()
        if row is None:
            return None
        return {**row, "created_at": _iso(row["created_at"])}

    def issue_admin_key(self, operator_id: str, *, label: str | None = None, scopes: Iterable[str] | None = None) -> dict[str, Any]:
        import secrets

        operator = self.get_operator(operator_id)
        if operator is None or operator["status"] != "active":
            raise OperatorAuthError("operator is missing or inactive")
        normalized_scopes = _normalize_admin_scopes(scopes)
        api_key = ADMIN_KEY_PREFIX + secrets.token_urlsafe(32)
        digest = _hash_key(api_key)
        key_id = "admin_gk_" + digest[:20]
        with self.backend.connect() as connection:
            connection.execute(
                """
                INSERT INTO operator_api_keys (key_id, operator_id, key_hash, label, scopes_json)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (key_id, operator_id, digest, label, json.dumps(normalized_scopes)),
            )
        return {"admin_api_key": api_key, "key_id": key_id, "operator_id": operator_id, "scopes": list(normalized_scopes)}

    def authenticate(self, api_key: str) -> dict[str, Any] | None:
        if not api_key or not api_key.startswith(ADMIN_KEY_PREFIX):
            return None
        with self.backend.connect() as connection:
            row = connection.execute(
                """
                SELECT k.key_id, k.operator_id, k.label, k.scopes_json, o.name AS operator_name
                FROM operator_api_keys AS k
                JOIN operators AS o ON o.operator_id = k.operator_id
                WHERE k.key_hash = %s AND k.status = 'active' AND o.status = 'active'
                """,
                (_hash_key(api_key),),
            ).fetchone()
        if row is None:
            return None
        identity = dict(row)
        identity["scopes"] = json.loads(identity.pop("scopes_json"))
        identity["identity_type"] = "operator"
        return identity

    def disable_admin_key(self, key_id: str) -> None:
        with self.backend.connect() as connection:
            row = connection.execute(
                """
                UPDATE operator_api_keys SET status = 'disabled', disabled_at = CURRENT_TIMESTAMP
                WHERE key_id = %s AND status = 'active' RETURNING key_id
                """,
                (key_id,),
            ).fetchone()
        if row is None:
            raise KeyError(key_id)


class NeonSigningKeyRegistry:
    def __init__(self, backend: NeonBackend):
        self.backend = backend

    def status(self, key_id: str, *, connection=None) -> str | None:
        owns = connection is None
        current = connection or self.backend.connect()
        try:
            row = current.execute(
                "SELECT event_type FROM signing_key_events WHERE key_id = %s ORDER BY event_id DESC LIMIT 1",
                (key_id,),
            ).fetchone()
            if row is None:
                return None
            return {"registered": "registered", "activated": "active", "retired": "retired", "revoked": "revoked"}[row["event_type"]]
        finally:
            if owns:
                current.close()

    def register(self, public_key_b64: str, *, label: str | None = None, activate: bool = True) -> dict[str, Any]:
        key_id = signing_key_id(public_key_b64)
        with self.backend.connect() as connection:
            existing = connection.execute(
                "SELECT public_key_b64 FROM signing_keys WHERE key_id = %s",
                (key_id,),
            ).fetchone()
            if existing and existing["public_key_b64"] != public_key_b64:
                raise SigningKeyRegistryError("key_id collision with different public key material")
            if not existing:
                connection.execute(
                    "INSERT INTO signing_keys (key_id, public_key_b64, algorithm, label) VALUES (%s, %s, 'Ed25519', %s)",
                    (key_id, public_key_b64, label),
                )
                connection.execute(
                    "INSERT INTO signing_key_events (key_id, event_type, metadata_json) VALUES (%s, 'registered', %s)",
                    (key_id, _json({"label": label})),
                )
            if activate and self.status(key_id, connection=connection) != "active":
                connection.execute(
                    "INSERT INTO signing_key_events (key_id, event_type) VALUES (%s, 'activated')",
                    (key_id,),
                )
        record = self.get(key_id)
        if record is None:
            raise SigningKeyRegistryError("registered key could not be read back")
        return record

    def transition(self, key_id: str, event_type: str, *, reason: str | None = None) -> dict[str, Any]:
        if event_type not in {"activated", "retired", "revoked"}:
            raise ValueError("event_type must be activated, retired, or revoked")
        if self.get(key_id) is None:
            raise KeyError(key_id)
        with self.backend.connect() as connection:
            connection.execute(
                "INSERT INTO signing_key_events (key_id, event_type, metadata_json) VALUES (%s, %s, %s)",
                (key_id, event_type, _json({"reason": reason})),
            )
        return self.get(key_id) or {}

    def get(self, key_id: str) -> dict[str, Any] | None:
        with self.backend.connect() as connection:
            row = connection.execute(
                "SELECT key_id, public_key_b64, algorithm, label, created_at FROM signing_keys WHERE key_id = %s",
                (key_id,),
            ).fetchone()
            if row is None:
                return None
            status = self.status(key_id, connection=connection)
        return {**row, "created_at": _iso(row["created_at"]), "status": status}

    def list(self) -> list[dict[str, Any]]:
        with self.backend.connect() as connection:
            rows = connection.execute("SELECT key_id FROM signing_keys ORDER BY created_at ASC, key_id ASC").fetchall()
        return [record for row in rows if (record := self.get(row["key_id"])) is not None]

    def events(self, key_id: str) -> list[dict[str, Any]]:
        if self.get(key_id) is None:
            raise KeyError(key_id)
        with self.backend.connect() as connection:
            rows = connection.execute(
                "SELECT event_id, event_type, metadata_json, created_at FROM signing_key_events WHERE key_id = %s ORDER BY event_id ASC",
                (key_id,),
            ).fetchall()
        return [
            {"event_id": row["event_id"], "event_type": row["event_type"], "metadata": json.loads(row["metadata_json"]), "created_at": _iso(row["created_at"])}
            for row in rows
        ]

    def assert_can_sign(self, key_id: str) -> dict[str, Any]:
        record = self.get(key_id)
        if record is None:
            raise SigningKeyRegistryError(f"signing key {key_id} is not registered")
        if record["status"] != "active":
            raise SigningKeyRegistryError(f"signing key {key_id} is {record['status']}, not active")
        return record


class NeonTenantPolicyStore:
    def __init__(self, backend: NeonBackend):
        self.backend = backend

    def create_version(self, tenant_id: str, policy: Mapping[str, Any], *, activate: bool = True, note: str | None = None) -> dict[str, Any]:
        normalized = normalize_policy(policy)
        policy_json = _json(normalized)
        digest = hashlib.sha256(policy_json.encode("utf-8")).hexdigest()
        with self.backend.connect() as connection:
            existing = connection.execute(
                "SELECT policy_id FROM tenant_policy_versions WHERE tenant_id = %s AND policy_hash = %s",
                (tenant_id, digest),
            ).fetchone()
            if existing:
                policy_id = existing["policy_id"]
            else:
                policy_id = f"policy_{uuid.uuid4().hex[:20]}"
                connection.execute(
                    "INSERT INTO tenant_policy_versions (policy_id, tenant_id, policy_hash, policy_json) VALUES (%s, %s, %s, %s)",
                    (policy_id, tenant_id, digest, policy_json),
                )
                connection.execute(
                    "INSERT INTO tenant_policy_events (tenant_id, policy_id, event_type, metadata_json) VALUES (%s, %s, 'created', %s)",
                    (tenant_id, policy_id, _json({"note": note})),
                )
            if activate:
                connection.execute(
                    "INSERT INTO tenant_policy_events (tenant_id, policy_id, event_type, metadata_json) VALUES (%s, %s, 'activated', %s)",
                    (tenant_id, policy_id, _json({"note": note})),
                )
        record = self.get(policy_id)
        if record is None:
            raise TenantPolicyError("policy version could not be read back")
        return record

    def activate(self, tenant_id: str, policy_id: str, *, note: str | None = None) -> dict[str, Any]:
        record = self.get(policy_id)
        if record is None or record["tenant_id"] != tenant_id:
            raise KeyError(policy_id)
        with self.backend.connect() as connection:
            connection.execute(
                "INSERT INTO tenant_policy_events (tenant_id, policy_id, event_type, metadata_json) VALUES (%s, %s, 'activated', %s)",
                (tenant_id, policy_id, _json({"note": note})),
            )
        return self.get(policy_id) or record

    def get(self, policy_id: str) -> dict[str, Any] | None:
        with self.backend.connect() as connection:
            row = connection.execute(
                "SELECT policy_id, tenant_id, policy_hash, policy_json, created_at FROM tenant_policy_versions WHERE policy_id = %s",
                (policy_id,),
            ).fetchone()
        if row is None:
            return None
        return {"policy_id": row["policy_id"], "tenant_id": row["tenant_id"], "policy_hash": row["policy_hash"], "policy": json.loads(row["policy_json"]), "created_at": _iso(row["created_at"])}

    def active_for(self, tenant_id: str) -> dict[str, Any]:
        with self.backend.connect() as connection:
            row = connection.execute(
                "SELECT policy_id FROM tenant_policy_events WHERE tenant_id = %s AND event_type = 'activated' ORDER BY event_id DESC LIMIT 1",
                (tenant_id,),
            ).fetchone()
        if row is None:
            return default_policy_record(tenant_id)
        return self.get(row["policy_id"]) or default_policy_record(tenant_id)

    def list_versions(self, tenant_id: str) -> list[dict[str, Any]]:
        active = self.active_for(tenant_id)["policy_id"]
        with self.backend.connect() as connection:
            rows = connection.execute(
                "SELECT policy_id FROM tenant_policy_versions WHERE tenant_id = %s ORDER BY created_at ASC, policy_id ASC",
                (tenant_id,),
            ).fetchall()
        records = []
        for row in rows:
            record = self.get(row["policy_id"])
            if record:
                records.append({**record, "active": record["policy_id"] == active})
        return records


class NeonReceiptStore:
    def __init__(self, backend: NeonBackend):
        self.backend = backend

    def save(self, verification_id: str, envelope: Mapping[str, Any], *, tenant_id: str | None = None) -> bool:
        payload_json = _receipt_json(envelope)
        payload_sha256 = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
        with self.backend.connect() as connection:
            existing = connection.execute(
                "SELECT payload_sha256, tenant_id FROM verification_receipts WHERE verification_id = %s FOR UPDATE",
                (verification_id,),
            ).fetchone()
            if existing:
                if existing["payload_sha256"] != payload_sha256 or existing["tenant_id"] != tenant_id:
                    raise ReceiptConflictError(f"verification_id {verification_id} already exists with different content or tenant ownership")
                return False
            connection.execute(
                "INSERT INTO verification_receipts (verification_id, payload_sha256, payload_json, tenant_id) VALUES (%s, %s, %s, %s)",
                (verification_id, payload_sha256, payload_json, tenant_id),
            )
        return True

    def get(self, verification_id: str, *, tenant_id: str | None = None) -> dict[str, Any] | None:
        with self.backend.connect() as connection:
            if tenant_id is None:
                row = connection.execute(
                    "SELECT payload_json FROM verification_receipts WHERE verification_id = %s AND tenant_id IS NULL",
                    (verification_id,),
                ).fetchone()
            else:
                row = connection.execute(
                    "SELECT payload_json FROM verification_receipts WHERE verification_id = %s AND tenant_id = %s",
                    (verification_id, tenant_id),
                ).fetchone()
        return json.loads(row["payload_json"]) if row else None

    def list_for_tenant(self, tenant_id: str, *, created_from: str | None = None, created_to: str | None = None, limit: int = 10000) -> list[dict[str, Any]]:
        if not 1 <= limit <= 10000:
            raise ValueError("limit must be between 1 and 10000")
        clauses = ["tenant_id = %s"]
        params: list[Any] = [tenant_id]
        if created_from:
            clauses.append("created_at >= %s::timestamptz")
            params.append(created_from)
        if created_to:
            clauses.append("created_at <= %s::timestamptz")
            params.append(created_to)
        params.append(limit)
        query = f"SELECT verification_id, payload_sha256, payload_json, created_at FROM verification_receipts WHERE {' AND '.join(clauses)} ORDER BY created_at ASC, verification_id ASC LIMIT %s"
        with self.backend.connect() as connection:
            rows = connection.execute(query, params).fetchall()
        records = []
        for row in rows:
            envelope = json.loads(row["payload_json"])
            actual = hashlib.sha256(_receipt_json(envelope).encode("utf-8")).hexdigest()
            records.append({
                "verification_id": row["verification_id"],
                "created_at": _iso(row["created_at"]),
                "payload_sha256": row["payload_sha256"],
                "payload_integrity_valid": actual == row["payload_sha256"],
                "envelope": envelope,
            })
        return records


class NeonRateLimiter:
    def __init__(self, backend: NeonBackend):
        self.backend = backend

    def consume(self, key_id: str, *, limit: int, window_seconds: int = 60, now: int | None = None) -> RateLimitDecision:
        if limit <= 0 or window_seconds <= 0:
            raise ValueError("limit and window_seconds must be positive")
        current = int(time.time() if now is None else now)
        bucket_start = current - (current % window_seconds)
        reset_at = bucket_start + window_seconds
        with self.backend.connect() as connection:
            connection.execute(
                "INSERT INTO api_rate_windows (key_id, bucket_start, count) VALUES (%s, %s, 0) ON CONFLICT DO NOTHING",
                (key_id, bucket_start),
            )
            row = connection.execute(
                "SELECT count FROM api_rate_windows WHERE key_id = %s AND bucket_start = %s FOR UPDATE",
                (key_id, bucket_start),
            ).fetchone()
            count = int(row["count"])
            if count >= limit:
                return RateLimitDecision(False, limit, 0, reset_at)
            new_count = count + 1
            connection.execute(
                "UPDATE api_rate_windows SET count = %s, updated_at = CURRENT_TIMESTAMP WHERE key_id = %s AND bucket_start = %s",
                (new_count, key_id, bucket_start),
            )
        return RateLimitDecision(True, limit, max(0, limit - new_count), reset_at)


class NeonAuditLifecycleStore:
    def __init__(self, backend: NeonBackend):
        self.backend = backend

    def register_export(self, package: Mapping[str, Any], *, tenant_id: str, created_by_key_id: str | None, retention_until: str | None = None) -> dict[str, Any]:
        manifest = dict(package.get("manifest") or {})
        package_id = str(manifest.get("package_id") or "")
        if not package_id:
            raise ValueError("audit package manifest is missing package_id")
        if manifest.get("tenant_id") != tenant_id:
            raise AuditLifecycleError("audit package tenant does not match lifecycle tenant")
        manifest_core = {key: value for key, value in manifest.items() if key != "generated_at"}
        manifest_sha256 = _sha256(manifest_core)
        with self.backend.connect() as connection:
            existing = connection.execute(
                "SELECT tenant_id, manifest_sha256 FROM audit_exports WHERE package_id = %s FOR UPDATE",
                (package_id,),
            ).fetchone()
            if existing:
                if existing["tenant_id"] != tenant_id or existing["manifest_sha256"] != manifest_sha256:
                    raise AuditLifecycleError("package_id already exists with different immutable export metadata")
            else:
                connection.execute(
                    """
                    INSERT INTO audit_exports
                        (package_id, tenant_id, manifest_sha256, manifest_json, retention_until, created_by_key_id)
                    VALUES (%s, %s, %s, %s, %s::timestamptz, %s)
                    """,
                    (package_id, tenant_id, manifest_sha256, _json(manifest), retention_until, created_by_key_id),
                )
                connection.execute(
                    """
                    INSERT INTO audit_export_events
                        (package_id, actor_type, actor_id, event_type, metadata_json)
                    VALUES (%s, 'service_key', %s, 'export_registered', %s)
                    """,
                    (package_id, created_by_key_id, _json({"retention_until": retention_until})),
                )
        record = self.get(package_id)
        if record is None:
            raise AuditLifecycleError("registered audit export could not be read back")
        return record

    def add_event(self, package_id: str, *, actor_type: str, actor_id: str | None, event_type: str, metadata: Mapping[str, Any] | None = None) -> dict[str, Any]:
        if actor_type not in {"operator", "service_key", "system"}:
            raise ValueError("unsupported actor_type")
        allowed = {"legal_hold_placed", "legal_hold_released", "retention_extended", "reviewed", "exported", "retention_eligible"}
        if event_type not in allowed:
            raise ValueError("unsupported audit lifecycle event_type")
        if self.get(package_id) is None:
            raise KeyError(package_id)
        payload = dict(metadata or {})
        with self.backend.connect() as connection:
            if event_type == "retention_extended":
                retention_until = payload.get("retention_until")
                if not retention_until:
                    raise ValueError("retention_extended requires retention_until")
                connection.execute(
                    "UPDATE audit_exports SET retention_until = %s::timestamptz WHERE package_id = %s",
                    (retention_until, package_id),
                )
            connection.execute(
                "INSERT INTO audit_export_events (package_id, actor_type, actor_id, event_type, metadata_json) VALUES (%s, %s, %s, %s, %s)",
                (package_id, actor_type, actor_id, event_type, _json(payload)),
            )
        return self.get(package_id) or {}

    def get(self, package_id: str) -> dict[str, Any] | None:
        with self.backend.connect() as connection:
            row = connection.execute(
                "SELECT package_id, tenant_id, manifest_sha256, manifest_json, retention_until, created_by_key_id, created_at FROM audit_exports WHERE package_id = %s",
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
            "package_id": row["package_id"], "tenant_id": row["tenant_id"], "manifest_sha256": row["manifest_sha256"],
            "manifest": json.loads(row["manifest_json"]), "retention_until": _iso(row["retention_until"]),
            "created_by_key_id": row["created_by_key_id"], "created_at": _iso(row["created_at"]),
            "legal_hold_active": hold_active, "events": events,
        }

    def events(self, package_id: str) -> list[dict[str, Any]]:
        with self.backend.connect() as connection:
            rows = connection.execute(
                "SELECT event_id, actor_type, actor_id, event_type, metadata_json, created_at FROM audit_export_events WHERE package_id = %s ORDER BY event_id ASC",
                (package_id,),
            ).fetchall()
        return [
            {"event_id": row["event_id"], "actor_type": row["actor_type"], "actor_id": row["actor_id"], "event_type": row["event_type"], "metadata": json.loads(row["metadata_json"]), "created_at": _iso(row["created_at"])}
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
            parsed = datetime.fromisoformat(str(retention_until).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            expired = now >= parsed
        return {
            "package_id": package_id,
            "retention_until": retention_until,
            "legal_hold_active": record["legal_hold_active"],
            "retention_expired": expired,
            "eligible_for_deletion": bool(expired and not record["legal_hold_active"]),
        }
