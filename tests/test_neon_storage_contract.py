from src import storage_backend
from src.neon_migrations import discover_migrations
from src.neon_rls import RLSNeonBackend
from src.trust_api import verify_payload


class _FakeRLSNeonBackend:
    def __init__(self, database_url, migration_database_url=None):
        self.database_url = database_url
        self.migration_database_url = migration_database_url
        self.schema_checked = False

    def assert_schema_current(self):
        self.schema_checked = True
        return {"pending": [], "drift": [], "unknown_applied_versions": []}


class _MemoryReceiptStore:
    def __init__(self):
        self.rows = {}

    def save(self, verification_id, envelope, *, tenant_id=None):
        self.rows[verification_id] = {"tenant_id": tenant_id, "envelope": envelope}
        return True


def _clear_backend_caches():
    storage_backend.neon_backend.cache_clear()
    storage_backend.operator_neon_backend.cache_clear()


def test_storage_mode_selects_neon_when_database_url_is_present(monkeypatch):
    monkeypatch.setenv("GAIALAB_DATABASE_URL", "postgresql://runtime.invalid/db")
    monkeypatch.setenv("GAIALAB_MIGRATION_DATABASE_URL", "postgresql://migration.invalid/db")
    monkeypatch.setattr(storage_backend, "RLSNeonBackend", _FakeRLSNeonBackend)
    _clear_backend_caches()
    try:
        assert storage_backend.storage_mode() == "neon"
        backend = storage_backend.neon_backend()
        assert backend.database_url == "postgresql://runtime.invalid/db"
        assert backend.migration_database_url == "postgresql://migration.invalid/db"
        assert backend.schema_checked is True
    finally:
        _clear_backend_caches()


def test_operator_backend_requires_separate_database_url(monkeypatch):
    monkeypatch.setenv("GAIALAB_DATABASE_URL", "postgresql://runtime.invalid/db")
    monkeypatch.delenv("GAIALAB_OPERATOR_DATABASE_URL", raising=False)
    monkeypatch.setattr(storage_backend, "RLSNeonBackend", _FakeRLSNeonBackend)
    _clear_backend_caches()
    try:
        assert storage_backend.operator_neon_backend() is None
        try:
            storage_backend.operator_registry()
        except RuntimeError as exc:
            assert "GAIALAB_OPERATOR_DATABASE_URL" in str(exc)
        else:  # pragma: no cover
            raise AssertionError("operator registry must fail closed without separate operator URL")
    finally:
        _clear_backend_caches()


def test_operator_backend_never_reuses_tenant_runtime_url(monkeypatch):
    monkeypatch.setenv("GAIALAB_DATABASE_URL", "postgresql://runtime.invalid/db")
    monkeypatch.setenv("GAIALAB_OPERATOR_DATABASE_URL", "postgresql://operator.invalid/db")
    monkeypatch.setenv("GAIALAB_MIGRATION_DATABASE_URL", "postgresql://migration.invalid/db")
    monkeypatch.setattr(storage_backend, "RLSNeonBackend", _FakeRLSNeonBackend)
    _clear_backend_caches()
    try:
        tenant_backend = storage_backend.neon_backend()
        operator_backend = storage_backend.operator_neon_backend()
        assert tenant_backend.database_url == "postgresql://runtime.invalid/db"
        assert operator_backend.database_url == "postgresql://operator.invalid/db"
        assert operator_backend.database_url != tenant_backend.database_url
    finally:
        _clear_backend_caches()


def test_rls_neon_backend_runtime_constructor_does_not_run_schema_ddl(monkeypatch):
    def _unexpected_migration_connect(*args, **kwargs):
        raise AssertionError("runtime backend construction must not run migration DDL")

    monkeypatch.setattr("src.neon_storage.psycopg.connect", _unexpected_migration_connect)
    backend = RLSNeonBackend(
        "postgresql://pooled.invalid/db",
        migration_database_url="postgresql://direct.invalid/db",
    )
    assert backend.database_url.endswith("/db")


def test_neon_migrations_are_ordered_and_checksummed():
    migrations = discover_migrations()
    assert [migration.version for migration in migrations] == ["0001", "0002", "0003"]
    assert all(len(migration.sha256) == 64 for migration in migrations)
    assert [migration.name for migration in migrations] == [
        "initial",
        "tenant_rls",
        "database_roles",
    ]


def test_rls_migrations_force_tenant_isolation_without_session_operator_bypass():
    rls_sql = discover_migrations()[1].sql
    role_sql = discover_migrations()[2].sql
    for table in (
        "verification_receipts",
        "tenant_policy_versions",
        "tenant_policy_events",
        "audit_exports",
        "audit_export_events",
    ):
        assert f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY" in rls_sql
        assert f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY" in rls_sql
    assert "current_setting('gaialab.tenant_id', true)" in rls_sql
    assert "SESSION_USER" in role_sql
    assert "gaialab_is_operator()" in role_sql
    assert "gaialab.operator_mode" not in role_sql


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
    _clear_backend_caches()
    try:
        assert storage_backend.storage_mode() == "sqlite"
    finally:
        _clear_backend_caches()
