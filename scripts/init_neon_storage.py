"""Initialize GaiaLab Trust Rail schema on Neon Postgres."""

from __future__ import annotations

import os

from src.neon_storage import NeonBackend, SCHEMA_VERSION


def main() -> None:
    runtime_url = os.getenv("GAIALAB_DATABASE_URL")
    if not runtime_url:
        raise SystemExit("GAIALAB_DATABASE_URL is required")
    migration_url = os.getenv("GAIALAB_MIGRATION_DATABASE_URL")
    NeonBackend(runtime_url, migration_database_url=migration_url)
    print(f"Initialized GaiaLab Trust Rail Neon schema: {SCHEMA_VERSION}")


if __name__ == "__main__":
    main()
