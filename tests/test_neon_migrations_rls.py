from pathlib import Path

from src.neon_migrations import discover_migrations
from src.neon_rls import clear_rls_context, current_rls_context, set_tenant_context


def test_neon_migrations_are_ordered_and_include_role_hardened_rls():
    migrations = discover_migrations()
    assert [migration.version for migration in migrations] == ["0001", "0002", "0003", "0004"]
    assert [migration.name for migration in migrations] == [
        "initial",
        "tenant_rls",
        "database_roles",
        "observability",
    ]

    rls_sql = migrations[1].sql
    for table in (
        "verification_receipts",
        "tenant_policy_versions",
        "tenant_policy_events",
        "audit_exports",
        "audit_export_events",
    ):
        assert f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY" in rls_sql
        assert f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY" in rls_sql

    role_sql = migrations[2].sql
    assert "gaialab_database_roles" in role_sql
    assert "gaialab_is_operator()" in role_sql
    assert "SESSION_USER" in role_sql
    assert "gaialab.operator_mode" not in role_sql

    observability_sql = migrations[3].sql
    assert "gaialab_current_role_kind" in observability_sql
    assert "SECURITY DEFINER" in observability_sql


def test_migration_checksums_are_stable_sha256_values():
    migrations = discover_migrations()
    assert migrations
    for migration in migrations:
        assert len(migration.sha256) == 64
        int(migration.sha256, 16)


def test_rls_context_is_tenant_only():
    clear_rls_context()
    assert current_rls_context() == {"tenant_id": None}
    set_tenant_context("tenant_a")
    assert current_rls_context() == {"tenant_id": "tenant_a"}
    clear_rls_context()
    assert current_rls_context() == {"tenant_id": None}


def test_migration_files_do_not_contain_database_credentials():
    migrations = discover_migrations()
    combined = "\n".join(migration.sql.lower() for migration in migrations)
    assert "postgresql://" not in combined
    assert "password=" not in combined
    assert "npg_" not in combined


def test_role_bootstrap_declares_no_privilege_escalation_flags():
    script = (Path(__file__).resolve().parent.parent / "scripts" / "configure_neon_roles.py").read_text(encoding="utf-8")
    assert "NOSUPERUSER" in script
    assert "NOBYPASSRLS" in script
    assert "NOCREATEDB" in script
    assert "NOCREATEROLE" in script
    assert "GAIALAB_RUNTIME_ROLE_PASSWORD" in script
    assert "GAIALAB_OPERATOR_ROLE_PASSWORD" in script
    assert "gaialab_schema_migrations" in script
    assert "postgresql://" not in script
