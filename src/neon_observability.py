"""Safe database observability for GaiaLab Neon runtime."""
from __future__ import annotations
from dataclasses import dataclass
import threading, time
from typing import Any
from src.neon_migrations import migration_status

@dataclass
class _FailureCounters:
    connection_failures: int = 0
    query_failures: int = 0
    readiness_failures: int = 0
    last_failure_at_unix: int | None = None

_lock = threading.Lock(); _counters = _FailureCounters()

def record_database_failure(kind: str) -> None:
    with _lock:
        if kind == "connection": _counters.connection_failures += 1
        elif kind == "query": _counters.query_failures += 1
        elif kind == "readiness": _counters.readiness_failures += 1
        else: raise ValueError("invalid database failure kind")
        _counters.last_failure_at_unix = int(time.time())

def failure_snapshot() -> dict[str, Any]:
    with _lock:
        return {"connection_failures": _counters.connection_failures, "query_failures": _counters.query_failures, "readiness_failures": _counters.readiness_failures, "last_failure_at_unix": _counters.last_failure_at_unix}

def probe_backend(backend, *, expected_role_kind: str) -> dict[str, Any]:
    started=time.perf_counter()
    try: connection=backend.connect()
    except Exception: record_database_failure("connection"); raise
    connection_ms=round((time.perf_counter()-started)*1000,2)
    try:
        started=time.perf_counter()
        with connection:
            role=connection.execute("SELECT current_user AS role_name, rolsuper, rolcreaterole, rolcreatedb, rolbypassrls, rolcanlogin FROM pg_roles WHERE rolname=current_user").fetchone()
            role_kind=connection.execute("SELECT gaialab_current_role_kind() AS role_kind").fetchone()["role_kind"]
            database_time=connection.execute("SELECT CURRENT_TIMESTAMP AS database_time").fetchone()["database_time"]
        query_ms=round((time.perf_counter()-started)*1000,2)
    except Exception: record_database_failure("query"); raise
    safe=bool(role) and all(not bool(role[f]) for f in ("rolsuper","rolcreaterole","rolcreatedb","rolbypassrls")) and bool(role["rolcanlogin"])
    return {"connected":True,"connection_ms":connection_ms,"query_ms":query_ms,"database_time":database_time.isoformat(),"role":{"name":role["role_name"],"kind":role_kind,"safe":safe,"expected_kind":expected_role_kind,"expected_kind_matches":role_kind==expected_role_kind,"superuser":bool(role["rolsuper"]),"bypass_rls":bool(role["rolbypassrls"])}}

def readiness_report(*, tenant_backend, operator_backend=None) -> dict[str, Any]:
    try:
        tenant=probe_backend(tenant_backend, expected_role_kind="tenant_runtime")
        migrations=migration_status(tenant_backend.database_url)
        migration_ready=not (migrations["pending"] or migrations["drift"] or migrations["unknown_applied_versions"])
        operator=probe_backend(operator_backend, expected_role_kind="operator_runtime") if operator_backend else None
        ready=tenant["role"]["safe"] and tenant["role"]["expected_kind_matches"] and migration_ready and (operator is None or (operator["role"]["safe"] and operator["role"]["expected_kind_matches"]))
        if not ready: record_database_failure("readiness")
        return {"ready":bool(ready),"tenant_database":tenant,"operator_database":operator,"migrations":{"ready":migration_ready,"latest_available":migrations["latest_available"],"pending":list(migrations["pending"]),"drift":list(migrations["drift"]),"unknown_applied_versions":list(migrations["unknown_applied_versions"])},"failures":failure_snapshot()}
    except Exception: record_database_failure("readiness"); raise
