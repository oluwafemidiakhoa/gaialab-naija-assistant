from pathlib import Path

from src import storage_backend
from src.neon_migrations import discover_migrations
from src.neon_storage import NeonBackend
from src.trust_api import verify_payload


class _FakeNeonBackend:
    def __init__(self, database_url, migration_database_url=None):
        self.database_url = database_url
        self.migration_database_url = migration_database_url


class _MemoryReceiptStore:
    def __init__(self):
        self.rows = {}

    def save(self, verification_id, envelope, *, tenant_id=None):
        self.rows[verification_id] = {"tenant_id": tenant_id, "envelope": envelope}
        return True


def test_storage_mode_selects_neon_when_database_url_is_present(monkeypatch):
    monkeypatch.setenv("GAIALAB_DATABASE_URL", "postgresql://example.invalid/db")
    monkeypatch.setenv("GAIALAB_MIGRATION_DATABASE_URL", "postgresql://direct.invalid/db")
    monkeypatch.setattr(storage_backend, "NeonBackend", _FakeNeonBackend)
    storage_backend.neon_backend.cache_clear()
    try:
        assert storage_backend.storage_mode() == "neon"
        backend = storage_backend.neon_backend()
        assert backend.database_url == "postgresql://example.invalid/db"
        assert backend.migration_database_url == "postgresql://direct.invalid/db"
    finally:
        storage_backend.neon_backend.cache_clear()


def test_neon_backend_construction_does_not_connect_or_run_ddl(monkeypatch):
    called = False

    def _unexpected_connect(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("NeonBackend construction must not connect")

    monkeypatch.setattr("src.neon_storage.psycopg.connect", _unexpected_connect)
    backend = NeonBackend(
        "postgresql://pooled.invalid/db",
        migration_database_url="postgresql://direct.invalid/db",
    )
    assert backend.database_url.endswith("/db")
    assert called is False


def test_neon_migrations_are_ordered_and_checksummed():
    migrations = discover_migrations()
    assert [migration.version for migration in migrations] == ["0001", "0002"]
    assert all(len(migration.sha256) == 64 for migration in migrations)
    assert migrations[0].name == "initial"
    assert migrations[1].name == "tenant_rls"


def test_rls_migration_forces_tenant_isolation():
    migration = discover_migrations()[1]
    sql = migration.sql
    for table in (
        "verification_receipts",
        "tenant_policy_versions",
        "tenant_policy_events",
        "audit_exports",
        "audit_export_events",
    ):
        assert f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY" in sql
        assert f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY" in sql
    assert "current_setting('gaialab.tenant_id', true)" in sql
    assert "current_setting('gaialab.operator_mode', true)" in sql


def test_verify_payload_accepts_injected_production_store():
    store = _MemoryReceiptStore()
    result = verify_payload(
        {
            "assistant_response": "The transfer is still pending.",
            "authoritative_state": {"transaction_status": "pending"},
            "assistant_claims": {"transaction_status": "pending"},
            "model_name": "example-model",
        },
        tenant_id="tenant_neon",
        receipt_store_backend=store,
    )
    assert result["integrity"]["persisted"] is True
    verification_id = result["verification_receipt"]["verification_id"]
    assert store.rows[verification_id]["tenant_id"] == "tenant_neon"


def test_sqlite_remains_default_without_neon_url(monkeypatch):
    monkeypatch.delenv("GAIALAB_DATABASE_URL", raising=False)
    storage_backend.neon_backend.cache_clear()
    try:
        assert storage_backend.storage_mode() == "sqlite"
    finally:
        storage_backend.neon_backend.cache_clear()
