"""Separate operator/admin authentication for GaiaLab Naija Trust Rail.

Admin credentials are intentionally distinct from tenant service API keys. They
use a different prefix, registry, header, and scope namespace.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import secrets
import sqlite3
from typing import Any, Iterable
import uuid

ADMIN_KEY_PREFIX = "gaia_admin_"
ADMIN_SCOPES = frozenset(
    {
        "audit:lifecycle",
        "tenants:manage",
        "policies:manage",
        "signing-keys:manage",
    }
)
DEFAULT_ADMIN_SCOPES = ("audit:lifecycle",)


class OperatorAuthError(RuntimeError):
    """Raised when operator identity or key lifecycle rules are violated."""


def _hash_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def _normalize_scopes(scopes: Iterable[str] | None) -> tuple[str, ...]:
    values = tuple(sorted(set(scopes or DEFAULT_ADMIN_SCOPES)))
    unknown = sorted(set(values) - ADMIN_SCOPES)
    if unknown:
        raise ValueError(f"unsupported admin scopes: {', '.join(unknown)}")
    if not values:
        raise ValueError("at least one admin scope is required")
    return values


class OperatorRegistry:
    """SQLite-backed operator registry storing only hashed admin-key material."""

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
                CREATE TABLE IF NOT EXISTS operators (
                    operator_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS operator_api_keys (
                    key_id TEXT PRIMARY KEY,
                    operator_id TEXT NOT NULL,
                    key_hash TEXT NOT NULL UNIQUE,
                    label TEXT,
                    scopes_json TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    disabled_at TEXT,
                    FOREIGN KEY(operator_id) REFERENCES operators(operator_id)
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_operator_keys_operator ON operator_api_keys(operator_id, status)"
            )

    def create_operator(self, name: str, operator_id: str | None = None) -> dict[str, Any]:
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("operator name must not be empty")
        operator_id = operator_id or f"operator_{uuid.uuid4().hex[:16]}"
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO operators (operator_id, name) VALUES (?, ?)",
                (operator_id, clean_name),
            )
        record = self.get_operator(operator_id)
        if record is None:  # pragma: no cover
            raise OperatorAuthError("created operator could not be read back")
        return record

    def get_operator(self, operator_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT operator_id, name, status, created_at FROM operators WHERE operator_id = ?",
                (operator_id,),
            ).fetchone()
        return dict(row) if row else None

    def issue_admin_key(
        self,
        operator_id: str,
        *,
        label: str | None = None,
        scopes: Iterable[str] | None = None,
    ) -> dict[str, Any]:
        operator = self.get_operator(operator_id)
        if operator is None or operator["status"] != "active":
            raise OperatorAuthError("operator is missing or inactive")
        normalized_scopes = _normalize_scopes(scopes)
        api_key = ADMIN_KEY_PREFIX + secrets.token_urlsafe(32)
        digest = _hash_key(api_key)
        key_id = "admin_gk_" + digest[:20]
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO operator_api_keys (
                    key_id, operator_id, key_hash, label, scopes_json
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    key_id,
                    operator_id,
                    digest,
                    label,
                    json.dumps(normalized_scopes, separators=(",", ":")),
                ),
            )
        return {
            "admin_api_key": api_key,
            "key_id": key_id,
            "operator_id": operator_id,
            "scopes": list(normalized_scopes),
        }

    def authenticate(self, api_key: str) -> dict[str, Any] | None:
        if not api_key or not api_key.startswith(ADMIN_KEY_PREFIX):
            return None
        digest = _hash_key(api_key)
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT k.key_id, k.operator_id, k.label, k.scopes_json,
                       o.name AS operator_name
                FROM operator_api_keys AS k
                JOIN operators AS o ON o.operator_id = k.operator_id
                WHERE k.key_hash = ?
                  AND k.status = 'active'
                  AND o.status = 'active'
                """,
                (digest,),
            ).fetchone()
        if row is None:
            return None
        identity = dict(row)
        identity["scopes"] = json.loads(identity.pop("scopes_json"))
        identity["identity_type"] = "operator"
        return identity

    def disable_admin_key(self, key_id: str) -> None:
        with self._connect() as connection:
            changed = connection.execute(
                """
                UPDATE operator_api_keys
                SET status = 'disabled', disabled_at = CURRENT_TIMESTAMP
                WHERE key_id = ? AND status = 'active'
                """,
                (key_id,),
            ).rowcount
        if not changed:
            raise KeyError(key_id)


def require_admin_scope(identity: dict[str, Any], scope: str) -> None:
    if scope not in ADMIN_SCOPES:
        raise ValueError(f"unknown admin scope: {scope}")
    if identity.get("identity_type") != "operator":
        raise PermissionError("operator identity is required")
    if scope not in set(identity.get("scopes") or []):
        raise PermissionError(f"admin key is missing required scope: {scope}")
