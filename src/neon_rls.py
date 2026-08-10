"""Request-scoped Row Level Security context for GaiaLab Neon storage."""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any

from src.neon_migrations import discover_migrations, migration_status
from src.neon_storage import NeonBackend, NeonOperatorRegistry, NeonTenantRegistry


_tenant_context: ContextVar[str | None] = ContextVar("gaialab_tenant_id", default=None)
_operator_context: ContextVar[bool] = ContextVar("gaialab_operator_mode", default=False)


def clear_rls_context() -> None:
    _tenant_context.set(None)
    _operator_context.set(False)


def set_tenant_context(tenant_id: str) -> None:
    if not tenant_id:
        raise ValueError("tenant_id must not be empty")
    _tenant_context.set(tenant_id)
    _operator_context.set(False)


def set_operator_context() -> None:
    _tenant_context.set(None)
    _operator_context.set(True)


def current_rls_context() -> dict[str, Any]:
    return {
        "tenant_id": _tenant_context.get(),
        "operator_mode": _operator_context.get(),
    }


class RLSNeonBackend(NeonBackend):
    """Neon backend that requires versioned migrations and applies RLS context."""

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
        tenant_id = _tenant_context.get()
        operator_mode = _operator_context.get()
        connection.execute(
            "SELECT set_config('gaialab.tenant_id', %s, true)",
            (tenant_id or "",),
        )
        connection.execute(
            "SELECT set_config('gaialab.operator_mode', %s, true)",
            ("on" if operator_mode else "off",),
        )
        return connection


class RLSNeonTenantRegistry(NeonTenantRegistry):
    """Tenant authentication establishes the RLS tenant context on success."""

    def authenticate(self, api_key: str) -> dict[str, Any] | None:
        clear_rls_context()
        identity = super().authenticate(api_key)
        if identity is not None:
            set_tenant_context(identity["tenant_id"])
        return identity


class RLSNeonOperatorRegistry(NeonOperatorRegistry):
    """Operator authentication establishes explicit cross-tenant operator mode."""

    def authenticate(self, api_key: str) -> dict[str, Any] | None:
        clear_rls_context()
        identity = super().authenticate(api_key)
        if identity is not None:
            set_operator_context()
        return identity
