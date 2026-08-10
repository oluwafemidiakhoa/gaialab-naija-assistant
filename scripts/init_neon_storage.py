"""Apply versioned GaiaLab Trust Rail migrations to Neon Postgres."""

from __future__ import annotations

import os

from src.neon_migrations import apply_migrations, migration_status


def main() -> None:
    runtime_url = os.getenv("GAIALAB_DATABASE_URL")
    migration_url = os.getenv("GAIALAB_MIGRATION_DATABASE_URL") or runtime_url
    if not migration_url:
        raise SystemExit("GAIALAB_MIGRATION_DATABASE_URL or GAIALAB_DATABASE_URL is required")

    applied = apply_migrations(migration_url)
    status = migration_status(migration_url)
    print(
        "GaiaLab Neon migrations complete: "
        f"applied_now={applied or 'none'} latest={status['latest_available']} pending={status['pending']}"
    )


if __name__ == "__main__":
    main()
