from pathlib import Path

import pytest

from src.neon_migrations import discover_migrations
from src.neon_rls import (
    clear_rls_context,
    current_rls_context,
    set_operator_context,
    set_tenant_context,
)


def test_neon_migrations_are_ordered_and_include_rls():
    migrations = discover_migrations()
    assert [migration.version for migration in migrations][:2] == ["0001", "0002"]
    assert migrations[0].name == "initial"
    assert migrations[1].name == "tenant_rls"

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

    assert "gaialab.tenant_id" in rls_sql
    assert "gaialab.operator_mode" in rls_sql


def test_migration_checksums_are_stable_sha256_values():
    migrations = discover_migrations()
    assert migrations
    for migration in migrations:
        assert len(migration.sha256) == 64
        int(migration.sha256, 16)


def test_rls_context_switches_between_tenant_and_operator():
    clear_rls_context()
    assert current_rls_context() == {"tenant_id": None, "operator_mode": False}

    set_tenant_context("tenant_a")
    assert current_rls_context() == {"tenant_id": "tenant_a", "operator_mode": False}

    set_operator_context()
    assert current_rls_context() == {"tenant_id": None, "operator_mode": True}

    clear_rls_context()
    assert current_rls_context() == {"tenant_id": None, "operator_mode": False}


def test_migration_files_do_not_contain_database_credentials():
    migrations = discover_migrations()
    combined = "\n".join(migration.sql.lower() for migration in migrations)
    assert "postgresql://" not in combined
    assert "password=" not in combined
    assert "npg_" not in combined
