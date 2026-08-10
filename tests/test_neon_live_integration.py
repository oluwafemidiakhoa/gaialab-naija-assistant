from __future__ import annotations

import os
import uuid

import psycopg
import pytest
from psycopg.rows import dict_row

from src.neon_migrations import apply_migrations, migration_status


MIGRATION_URL = os.getenv("NEON_TEST_MIGRATION_DATABASE_URL")
RUNTIME_URL = os.getenv("NEON_TEST_RUNTIME_DATABASE_URL")
OPERATOR_URL = os.getenv("NEON_TEST_OPERATOR_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not (MIGRATION_URL and RUNTIME_URL and OPERATOR_URL),
    reason="live Neon test URLs are not configured",
)


def _role_flags(database_url: str) -> dict[str, object]:
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        return dict(
            connection.execute(
                """
                SELECT current_user AS role_name, rolsuper, rolcreaterole,
                       rolcreatedb, rolbypassrls, rolcanlogin
                FROM pg_roles WHERE rolname = current_user
                """
            ).fetchone()
        )


def test_live_neon_migrations_are_current():
    apply_migrations(MIGRATION_URL)
    status = migration_status(MIGRATION_URL)
    assert status["pending"] == []
    assert status["drift"] == []
    assert status["unknown_applied_versions"] == []


def test_live_runtime_and_operator_roles_are_least_privilege():
    for database_url in (RUNTIME_URL, OPERATOR_URL):
        flags = _role_flags(database_url)
        assert flags["rolcanlogin"] is True
        assert flags["rolsuper"] is False
        assert flags["rolcreaterole"] is False
        assert flags["rolcreatedb"] is False
        assert flags["rolbypassrls"] is False


def test_live_tenant_rls_and_operator_audit_access():
    suffix = uuid.uuid4().hex
    tenant_a = f"tenant_ci_a_{suffix}"
    tenant_b = f"tenant_ci_b_{suffix}"
    package_id = f"audit_ci_{suffix}"
    verification_id = f"verify_ci_{suffix}"

    try:
        with psycopg.connect(RUNTIME_URL, row_factory=dict_row) as connection:
            connection.execute("SELECT set_config('gaialab.tenant_id', %s, true)", (tenant_a,))
            connection.execute(
                """
                INSERT INTO verification_receipts
                    (verification_id, payload_sha256, payload_json, tenant_id)
                VALUES (%s, %s, %s, %s)
                """,
                (verification_id, "0" * 64, "{}", tenant_a),
            )
            connection.execute(
                """
                INSERT INTO audit_exports
                    (package_id, tenant_id, manifest_sha256, manifest_json)
                VALUES (%s, %s, %s, %s)
                """,
                (package_id, tenant_a, "1" * 64, "{}"),
            )

        with psycopg.connect(RUNTIME_URL, row_factory=dict_row) as connection:
            connection.execute("SELECT set_config('gaialab.tenant_id', %s, true)", (tenant_b,))
            hidden_receipt = connection.execute(
                "SELECT verification_id FROM verification_receipts WHERE verification_id = %s",
                (verification_id,),
            ).fetchone()
            hidden_export = connection.execute(
                "SELECT package_id FROM audit_exports WHERE package_id = %s",
                (package_id,),
            ).fetchone()
            assert hidden_receipt is None
            assert hidden_export is None

            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                connection.execute(
                    """
                    INSERT INTO verification_receipts
                        (verification_id, payload_sha256, payload_json, tenant_id)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (f"blocked_{suffix}", "2" * 64, "{}", tenant_a),
                )

        with psycopg.connect(OPERATOR_URL, row_factory=dict_row) as connection:
            visible = connection.execute(
                "SELECT package_id, tenant_id FROM audit_exports WHERE package_id = %s",
                (package_id,),
            ).fetchone()
            assert visible is not None
            assert visible["tenant_id"] == tenant_a
            connection.execute(
                """
                INSERT INTO audit_export_events
                    (package_id, actor_type, actor_id, event_type, metadata_json)
                VALUES (%s, 'operator', 'ci', 'reviewed', '{}')
                """,
                (package_id,),
            )
    finally:
        with psycopg.connect(MIGRATION_URL) as connection:
            connection.execute("SELECT set_config('gaialab.tenant_id', %s, true)", (tenant_a,))
            connection.execute("DELETE FROM audit_export_events WHERE package_id = %s", (package_id,))
            connection.execute("DELETE FROM audit_exports WHERE package_id = %s", (package_id,))
            connection.execute(
                "DELETE FROM verification_receipts WHERE verification_id IN (%s, %s)",
                (verification_id, f"blocked_{suffix}"),
            )
