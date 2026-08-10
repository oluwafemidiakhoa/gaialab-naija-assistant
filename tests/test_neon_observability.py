from src import neon_observability


class _Backend:
    database_url = "postgresql://runtime.invalid/db"


def test_failure_counters_are_aggregate_only():
    neon_observability.reset_failure_counters()
    neon_observability.record_database_failure("connection")
    neon_observability.record_database_failure("query")
    snapshot = neon_observability.failure_snapshot()
    assert snapshot["connection_failures"] == 1
    assert snapshot["query_failures"] == 1
    assert set(snapshot) == {
        "connection_failures",
        "query_failures",
        "readiness_failures",
        "last_failure_at_unix",
    }


def test_readiness_uses_runtime_database_url_not_migration_owner(monkeypatch):
    tenant = _Backend()
    tenant.migration_database_url = "postgresql://owner.invalid/db"
    seen = {}

    monkeypatch.setattr(
        neon_observability,
        "probe_backend",
        lambda backend, expected_role_kind: {
            "connected": True,
            "role": {
                "safe": True,
                "expected_kind_matches": True,
            },
        },
    )

    def _status(url):
        seen["url"] = url
        return {
            "pending": [],
            "drift": [],
            "unknown_applied_versions": [],
            "latest_available": "0004",
        }

    monkeypatch.setattr(neon_observability, "migration_status", _status)
    report = neon_observability.readiness_report(tenant_backend=tenant)
    assert report["ready"] is True
    assert seen["url"] == tenant.database_url
    assert seen["url"] != tenant.migration_database_url


def test_readiness_fails_closed_on_unsafe_role(monkeypatch):
    neon_observability.reset_failure_counters()
    tenant = _Backend()
    monkeypatch.setattr(
        neon_observability,
        "probe_backend",
        lambda backend, expected_role_kind: {
            "connected": True,
            "role": {
                "safe": False,
                "expected_kind_matches": True,
            },
        },
    )
    monkeypatch.setattr(
        neon_observability,
        "migration_status",
        lambda url: {
            "pending": [],
            "drift": [],
            "unknown_applied_versions": [],
            "latest_available": "0004",
        },
    )
    report = neon_observability.readiness_report(tenant_backend=tenant)
    assert report["ready"] is False
    assert report["failures"]["readiness_failures"] == 1
