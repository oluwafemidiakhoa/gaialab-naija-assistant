"""Safe database observability for GaiaLab Neon runtime.

The probe surface exposes only aggregate health metadata: role flags, migration
state, connectivity/query latency, and process-local failure counters. It never
returns database URLs, SQL text, tenant IDs, receipts, prompts, or evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
import threading
import time
from typing import Any

from psycopg.rows import dict_row

from src.neon_migrations import migration_status


@dataclass
class _FailureCounters:
    connection_failures: int = 0
    query_failures: int = 0
    readiness_failures: int = 0
    last_failure_at_unix: int | None = None


_lock = threading.Lock()
_counters = _FailureCounters()


def record_database_failure(kind: str) -> None:
    now = int(time.time())
    with _lock:
        if kind == "connection":
            _counters.connection_failures += 1
        elif kind == "query":
            _counters.query_failures += 1
        elif kind == "readiness":
            _counters.readiness_failures += 1
        else:
            raise ValueError("database failure kind must be connection, query, or readiness")
        _counters.last_failure_at_unix = now


def failure_snapshot() -> dict[str, Any]:
    with _lock:
        return {
            "connection_failures": _counters.connection_failures,
            "query_failures": _counters.query_failures,
            "readiness_failures": _counters.readiness_failures,
            "last_failure_at_unix": _counters.last_failure_at_unix,
        }


def reset_failure_counters() -> None:
    """Test helper; runtime code should not reset counters."""
    global _counters
    with _lock:
        _counters = _FailureCounters()


def probe_backend(backend, *, expected_role_kind: str | None = None) -> dict[str, Any]:
    """Probe one configured backend without mutating application data."""
    started = time.perf_counter()
    try:
        connection = backend.connect()
    except Exception:
        record_database_failure("connection")
        raise

    connection_ms = round((time.perf_counter() - started) * 1000, 2)
    try:
        query_started = time.perf_counter()
        with connection:
            row = connection.execute(
                """
                SELECT current_user AS role_name,
                       rolsuper,
                       rolcreaterole,
                       rolcreatedb,
                       rolbypassrls,
                       rolcanlogin
                FROM pg_roles
                WHERE rolname = current_user
                """
            ).fetchone()
            database_time = connection.execute(
                "SELECT CURRENT_TIMESTAMP AS database_time"
            ).fetchone()["database_time"]
            role_kind_row = connection.execute(
                """
                SELECT role_kind
                FROM gaialab_database_roles
                WHERE role_name = SESSION_USER
                """
            ).fetchone()
        query_ms = round((time.perf_counter() - query_started) * 1000, 2)
    except Exception:
        record_database_failure("query")
        raise

    role = dict(row or {})
    role_kind = role_kind_row["role_kind"] if role_kind_row else None
    safe_role = bool(role) and all(
        not bool(role.get(flag))
        for flag in ("rolsuper", "rolcreaterole", "rolcreatedb", "rolbypassrls")
    ) and bool(role.get("rolcanlogin"))
    role_kind_matches = expected_role_kind is None or role_kind == expected_role_kind

    return {
        "connected": True,
        "connection_ms": connection_ms,
        "query_ms": query_ms,
        "database_time": database_time.isoformat() if hasattr(database_time, "isoformat") else str(database_time),
        "role": {
            "name": role.get("role_name"),
            "kind": role_kind,
            "safe": safe_role,
            "expected_kind": expected_role_kind,
            "expected_kind_matches": role_kind_matches,
            "superuser": bool(role.get("rolsuper")),
            "bypass_rls": bool(role.get("rolbypassrls")),
            "create_role": bool(role.get("rolcreaterole")),
            "create_database": bool(role.get("rolcreatedb")),
        },
    }


def readiness_report(*, tenant_backend, operator_backend=None) -> dict[str, Any]:
    """Return fail-closed readiness details for configured Neon backends."""
    try:
        tenant_probe = probe_backend(tenant_backend, expected_role_kind="tenant_runtime")
        migrations = migration_status(tenant_backend.migration_database_url)
        migration_ready = not (
            migrations["pending"]
            or migrations["drift"]
            or migrations["unknown_applied_versions"]
        )

        operator_probe = None
        if operator_backend is not None:
            operator_probe = probe_backend(operator_backend, expected_role_kind="operator_runtime")

        ready = bool(
            tenant_probe["role"]["safe"]
            and tenant_probe["role"]["expected_kind_matches"]
            and migration_ready
            and (
                operator_probe is None
                or (
                    operator_probe["role"]["safe"]
                    and operator_probe["role"]["expected_kind_matches"]
                )
            )
        )
        if not ready:
            record_database_failure("readiness")

        return {
            "ready": ready,
            "tenant_database": tenant_probe,
            "operator_database": operator_probe,
            "migrations": {
                "ready": migration_ready,
                "latest_available": migrations["latest_available"],
                "pending": list(migrations["pending"]),
                "drift": list(migrations["drift"]),
                "unknown_applied_versions": list(migrations["unknown_applied_versions"]),
            },
            "failures": failure_snapshot(),
        }
    except Exception:
        record_database_failure("readiness")
        raise
