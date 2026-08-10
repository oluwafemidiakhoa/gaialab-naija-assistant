"""Tenant and API-key registry for GaiaLab Naija Trust API."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import secrets
import sqlite3
from typing import Any, Iterable
import uuid

API_KEY_PREFIX = "gaia_live_"
DEFAULT_SCOPES = ("verification:write", "receipts:read")
ALLOWED_SCOPES = frozenset({"verification:write", "receipts:read", "audit:export"})


class TenantAuthError(RuntimeError):
    """Raised when tenant or API-key lifecycle rules are violated."""


def _hash_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def _normalize_scopes(scopes: Iterable[str] | None) -> tuple[str, ...]:
    values = tuple(sorted(set(scopes or DEFAULT_SCOPES)))
    unknown = sorted(set(values) - ALLOWED_SCOPES)
    if unknown:
        raise ValueError(f"unsupported API-key scopes: {', '.join(unknown)}")
    if not values:
        raise ValueError("at least one API-key scope is required")
    return values


class TenantRegistry:
    """SQLite-backed tenant registry storing only hashed API-key material."""

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
                CREATE TABLE IF NOT EXISTS tenants (
                    tenant_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS tenant_api_keys (
                    key_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    key_hash TEXT NOT NULL UNIQUE,
                    label TEXT,
                    scopes_json TEXT NOT NULL DEFAULT '[\"verification:write\",\"receipts:read\"]',
                    rate_limit_per_minute INTEGER NOT NULL DEFAULT 120,
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    disabled_at TEXT,
                    FOREIGN KEY(tenant_id) REFERENCES tenants(tenant_id)
                )
                """
            )
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(tenant_api_keys)")}
            if "scopes_json" not in columns:
                connection.execute(
                    "ALTER TABLE tenant_api_keys ADD COLUMN scopes_json TEXT NOT NULL DEFAULT '[\"verification:write\",\"receipts:read\"]'"
                )
            if "rate_limit_per_minute" not in columns:
                connection.execute(
                    "ALTER TABLE tenant_api_keys ADD COLUMN rate_limit_per_minute INTEGER NOT NULL DEFAULT 120"
                )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_tenant_api_keys_tenant ON tenant_api_keys(tenant_id, status)"
            )

    def create_tenant(self, name: str, tenant_id: str | None = None) -> dict[str, Any]:
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("tenant name must not be empty")
        tenant_id = tenant_id or f"tenant_{uuid.uuid4().hex[:16]}"
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO tenants (tenant_id, name) VALUES (?, ?)",
                (tenant_id, clean_name),
            )
        record = self.get_tenant(tenant_id)
        if record is None:  # pragma: no cover
            raise TenantAuthError("created tenant could not be read back")
        return record

    def get_tenant(self, tenant_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT tenant_id, name, status, created_at FROM tenants WHERE tenant_id = ?",
                (tenant_id,),
            ).fetchone()
        return dict(row) if row else None

    def issue_api_key(
        self,
        tenant_id: str,
        *,
        label: str | None = None,
        scopes: Iterable[str] | None = None,
        rate_limit_per_minute: int = 120,
    ) -> dict[str, Any]:
        tenant = self.get_tenant(tenant_id)
        if tenant is None or tenant["status"] != "active":
            raise TenantAuthError("tenant is missing or inactive")
        normalized_scopes = _normalize_scopes(scopes)
        if not isinstance(rate_limit_per_minute, int) or isinstance(rate_limit_per_minute, bool) or rate_limit_per_minute <= 0:
            raise ValueError("rate_limit_per_minute must be a positive integer")
        api_key = API_KEY_PREFIX + secrets.token_urlsafe(32)
        digest = _hash_key(api_key)
        key_id = "gk_" + digest[:20]
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO tenant_api_keys (
                    key_id, tenant_id, key_hash, label, scopes_json, rate_limit_per_minute
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    key_id,
                    tenant_id,
                    digest,
                    label,
                    json.dumps(normalized_scopes, separators=(",", ":")),
                    rate_limit_per_minute,
                ),
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
        digest = _hash_key(api_key)
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT k.key_id, k.tenant_id, k.label, k.scopes_json,
                       k.rate_limit_per_minute, t.name AS tenant_name
                FROM tenant_api_keys AS k
                JOIN tenants AS t ON t.tenant_id = k.tenant_id
                WHERE k.key_hash = ?
                  AND k.status = 'active'
                  AND t.status = 'active'
                """,
                (digest,),
            ).fetchone()
        if row is None:
            return None
        identity = dict(row)
        identity["scopes"] = json.loads(identity.pop("scopes_json"))
        return identity

    def disable_api_key(self, key_id: str) -> None:
        with self._connect() as connection:
            changed = connection.execute(
                """
                UPDATE tenant_api_keys
                SET status = 'disabled', disabled_at = CURRENT_TIMESTAMP
                WHERE key_id = ? AND status = 'active'
                """,
                (key_id,),
            ).rowcount
        if not changed:
            raise KeyError(key_id)


def require_scope(identity: dict[str, Any], scope: str) -> None:
    if scope not in ALLOWED_SCOPES:
        raise ValueError(f"unknown scope: {scope}")
    if scope not in set(identity.get("scopes") or []):
        raise PermissionError(f"API key is missing required scope: {scope}")
