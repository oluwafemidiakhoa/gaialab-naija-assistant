"""Create and verify least-privilege Neon roles for GaiaLab Trust Rail.

Run with the migration/owner connection only. Passwords and connection strings are
read from environment variables and are never written to repository files.
"""

from __future__ import annotations

import os

import psycopg
from psycopg import sql
from psycopg.rows import dict_row


RUNTIME_TABLE_PRIVILEGES = {
    "tenants": ("SELECT",),
    "tenant_api_keys": ("SELECT",),
    "signing_keys": ("SELECT",),
    "signing_key_events": ("SELECT",),
    "tenant_policy_versions": ("SELECT",),
    "tenant_policy_events": ("SELECT",),
    "verification_receipts": ("SELECT", "INSERT"),
    "api_rate_windows": ("SELECT", "INSERT", "UPDATE"),
    "audit_exports": ("SELECT", "INSERT"),
    "audit_export_events": ("SELECT", "INSERT"),
}

OPERATOR_TABLE_PRIVILEGES = {
    "operators": ("SELECT",),
    "operator_api_keys": ("SELECT",),
    "audit_exports": ("SELECT", "UPDATE"),
    "audit_export_events": ("SELECT", "INSERT"),
}

SEQUENCE_USAGE_ROLES = {
    "runtime": ("tenant_policy_events_event_id_seq", "audit_export_events_event_id_seq"),
    "operator": ("audit_export_events_event_id_seq",),
}


def _required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise SystemExit(f"{name} is required")
    return value


def _ensure_login_role(connection, role_name: str, password: str) -> None:
    exists = connection.execute(
        "SELECT 1 FROM pg_roles WHERE rolname = %s",
        (role_name,),
    ).fetchone()
    if exists:
        connection.execute(
            sql.SQL(
                "ALTER ROLE {} WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS PASSWORD %s"
            ).format(sql.Identifier(role_name)),
            (password,),
        )
    else:
        connection.execute(
            sql.SQL(
                "CREATE ROLE {} WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS PASSWORD %s"
            ).format(sql.Identifier(role_name)),
            (password,),
        )


def _grant_table_privileges(connection, role_name: str, grants: dict[str, tuple[str, ...]]) -> None:
    connection.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(role_name)))
    for table, privileges in grants.items():
        connection.execute(
            sql.SQL("REVOKE ALL ON TABLE {} FROM {}").format(
                sql.Identifier(table), sql.Identifier(role_name)
            )
        )
        connection.execute(
            sql.SQL("GRANT {} ON TABLE {} TO {}").format(
                sql.SQL(", ").join(sql.SQL(privilege) for privilege in privileges),
                sql.Identifier(table),
                sql.Identifier(role_name),
            )
        )


def _grant_sequence_usage(connection, role_name: str, sequence_names: tuple[str, ...]) -> None:
    for sequence_name in sequence_names:
        connection.execute(
            sql.SQL("GRANT USAGE, SELECT ON SEQUENCE {} TO {}").format(
                sql.Identifier(sequence_name), sql.Identifier(role_name)
            )
        )


def _register_database_role(connection, role_name: str, role_kind: str) -> None:
    connection.execute(
        """
        INSERT INTO gaialab_database_roles (role_name, role_kind)
        VALUES (%s, %s)
        ON CONFLICT (role_name)
        DO UPDATE SET role_kind = EXCLUDED.role_kind
        """,
        (role_name, role_kind),
    )


def _assert_safe_role(connection, role_name: str) -> dict[str, object]:
    row = connection.execute(
        """
        SELECT rolname, rolsuper, rolcreaterole, rolcreatedb, rolbypassrls, rolcanlogin
        FROM pg_roles WHERE rolname = %s
        """,
        (role_name,),
    ).fetchone()
    if row is None:
        raise RuntimeError(f"role {role_name} was not created")
    unsafe = [
        field
        for field in ("rolsuper", "rolcreaterole", "rolcreatedb", "rolbypassrls")
        if row[field]
    ]
    if unsafe or not row["rolcanlogin"]:
        raise RuntimeError(f"role {role_name} is unsafe: {unsafe or ['cannot_login']}")
    return dict(row)


def main() -> None:
    migration_url = _required("GAIALAB_MIGRATION_DATABASE_URL")
    runtime_role = os.getenv("GAIALAB_RUNTIME_ROLE", "gaialab_runtime")
    operator_role = os.getenv("GAIALAB_OPERATOR_ROLE", "gaialab_operator")
    runtime_password = _required("GAIALAB_RUNTIME_ROLE_PASSWORD")
    operator_password = _required("GAIALAB_OPERATOR_ROLE_PASSWORD")

    with psycopg.connect(migration_url, row_factory=dict_row) as connection:
        database_name = connection.execute("SELECT current_database() AS name").fetchone()["name"]
        for role_name, password in (
            (runtime_role, runtime_password),
            (operator_role, operator_password),
        ):
            _ensure_login_role(connection, role_name, password)
            connection.execute(
                sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                    sql.Identifier(database_name), sql.Identifier(role_name)
                )
            )

        _grant_table_privileges(connection, runtime_role, RUNTIME_TABLE_PRIVILEGES)
        _grant_table_privileges(connection, operator_role, OPERATOR_TABLE_PRIVILEGES)
        _grant_sequence_usage(connection, runtime_role, SEQUENCE_USAGE_ROLES["runtime"])
        _grant_sequence_usage(connection, operator_role, SEQUENCE_USAGE_ROLES["operator"])
        _register_database_role(connection, runtime_role, "tenant_runtime")
        _register_database_role(connection, operator_role, "operator_runtime")

        runtime_status = _assert_safe_role(connection, runtime_role)
        operator_status = _assert_safe_role(connection, operator_role)

    print(
        "Configured Neon roles: "
        f"runtime={runtime_status['rolname']} operator={operator_status['rolname']} "
        "superuser=false bypassrls=false"
    )


if __name__ == "__main__":
    main()
