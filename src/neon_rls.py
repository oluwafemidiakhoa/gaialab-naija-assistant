"""Tenant Row Level Security context for GaiaLab Neon storage."""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any

from src.neon_migrations import migration_status
from src.neon_storage import NeonBackend, NeonTenantRegistry


_tenant_context: ContextVar[str | None] = ContextVar("gaialab_tenant_id", default=None)


def clear_rls_context() -> None:
    _tenant_context.set(None)


def set_tenant_context(tenant_id: str) -> None:
    if not tenant_id:
        raise ValueError("tenant_id must not be empty")
    _tenant_context.set(tenant_id)


def current_rls_context() -> dict[str, Any]:
    return {"tenant_id": _tenant_context.get()}


class RLSNeonBackend(NeonBackend):
    """Neon backend that requires versioned migrations and applies tenant RLS context."""

    def initialize(self) -> None:
        """Runtime startup never mutates schema; migrations are explicit."""
        return None

    def assert_schema_current(self) -> dict[str, object]:
        status = migration_status(self.migration_database_url)
        if status["drift"]:
            raise RuntimeError(
                "Neon migration checksum drift detected: " + ", ".join(status["drift"])
            )
        if status["pending"]:
            raise RuntimeError(
                "Neon schema has pending migrations: " + ", ".join(status["pending"])
            )
        if status["unknown_applied_versions"]:
            raise RuntimeError(
                "Neon database contains unknown applied migrations: "
                + ", ".join(status["unknown_applied_versions"])
            )
        return status

    def connect(self):
        connection = super().connect()
        connection.execute(
            "SELECT set_config('gaialab.tenant_id', %s, true)",
            (_tenant_context.get() or "",),
        )
        return connection


class RLSNeonTenantRegistry(NeonTenantRegistry):
    """Tenant authentication establishes the tenant context on success."""

    def authenticate(self, api_key: str) -> dict[str, Any] | None:
        clear_rls_context()
        identity = super().authenticate(api_key)
        if identity is not None:
            set_tenant_context(identity["tenant_id"])
        return identity
