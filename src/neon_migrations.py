"""Versioned SQL migration runner for GaiaLab Neon storage."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Iterable

import psycopg
from psycopg.rows import dict_row


MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations" / "neon"
MIGRATION_LOCK_ID = 684214727611


@dataclass(frozen=True)
class Migration:
    version: str
    name: str
    path: Path
    sha256: str
    sql: str


class MigrationDriftError(RuntimeError):
    """Raised when an already-applied migration file has changed."""


def discover_migrations(directory: Path = MIGRATIONS_DIR) -> list[Migration]:
    migrations: list[Migration] = []
    for path in sorted(directory.glob("*.sql")):
        stem = path.stem
        version, separator, name = stem.partition("_")
        if not separator or not version.isdigit():
            raise ValueError(f"invalid migration filename: {path.name}")
        sql = path.read_text(encoding="utf-8")
        migrations.append(
            Migration(
                version=version,
                name=name,
                path=path,
                sha256=hashlib.sha256(sql.encode("utf-8")).hexdigest(),
                sql=sql,
            )
        )
    versions = [migration.version for migration in migrations]
    if len(versions) != len(set(versions)):
        raise ValueError("duplicate Neon migration versions detected")
    return migrations


def _ensure_migration_table(connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS gaialab_schema_migrations (
            version TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            sha256 TEXT NOT NULL,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


def migration_status(database_url: str) -> dict[str, object]:
    migrations = discover_migrations()
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        _ensure_migration_table(connection)
        rows = connection.execute(
            "SELECT version, name, sha256, applied_at FROM gaialab_schema_migrations ORDER BY version"
        ).fetchall()
    applied = {row["version"]: row for row in rows}
    drift: list[str] = []
    pending: list[str] = []
    for migration in migrations:
        row = applied.get(migration.version)
        if row is None:
            pending.append(migration.version)
        elif row["sha256"] != migration.sha256:
            drift.append(migration.version)
    unknown = sorted(set(applied) - {migration.version for migration in migrations})
    return {
        "applied": rows,
        "pending": pending,
        "drift": drift,
        "unknown_applied_versions": unknown,
        "latest_available": migrations[-1].version if migrations else None,
    }


def apply_migrations(database_url: str, migrations: Iterable[Migration] | None = None) -> list[str]:
    ordered = list(migrations or discover_migrations())
    applied_now: list[str] = []
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        _ensure_migration_table(connection)
        connection.execute("SELECT pg_advisory_xact_lock(%s)", (MIGRATION_LOCK_ID,))
        existing_rows = connection.execute(
            "SELECT version, sha256 FROM gaialab_schema_migrations"
        ).fetchall()
        existing = {row["version"]: row["sha256"] for row in existing_rows}

        for migration in ordered:
            current_hash = existing.get(migration.version)
            if current_hash is not None:
                if current_hash != migration.sha256:
                    raise MigrationDriftError(
                        f"migration {migration.version} checksum changed after application"
                    )
                continue

            with connection.transaction():
                connection.execute(migration.sql)
                connection.execute(
                    """
                    INSERT INTO gaialab_schema_migrations (version, name, sha256)
                    VALUES (%s, %s, %s)
                    """,
                    (migration.version, migration.name, migration.sha256),
                )
            applied_now.append(migration.version)
            existing[migration.version] = migration.sha256

    return applied_now
