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
    """Neon backend that requires versioned migrations and applies tenant RLS context.

    The base Neon stores historically pass ``tenant_id=`` and ``operator=`` to
    ``connect``. The RLS backend accepts those arguments for call compatibility,
    but the ``operator`` flag is deliberately non-authoritative: operator access
    is derived only from the authenticated PostgreSQL ``SESSION_USER`` via the
    role registry installed by migration 0003.
    """

    def initialize(self) -> None:
        """Runtime startup never mutates schema; migrations are explicit."""
        return None

    def assert_schema_current(self) -> dict[str, object]:
        # Deliberately use the runtime identity. Runtime readiness must not depend
        # on access to the migration/owner credential.
        status = migration_status(self.database_url)
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

    def connect(
        self,
        *,
        tenant_id: str | None = None,
        operator: bool = False,
    ):
        """Open a runtime connection without any session-controlled operator bypass.

        ``operator`` is accepted only because inherited stores still pass it. It
        never sets ``gaialab.operator_mode`` and never changes authorization.
        Tenant scope may come from the explicit argument, the context variable,
        or both when they agree.
        """
        del operator  # authorization comes from SESSION_USER, never this flag
        contextual_tenant = _tenant_context.get()
        if tenant_id is not None and contextual_tenant not in (None, tenant_id):
            raise ValueError("tenant_id does not match active RLS context")
        effective_tenant = tenant_id if tenant_id is not None else contextual_tenant

        # Bypass NeonBackend.connect's legacy tenant/operator GUC handling. The
        # RLS backend owns the complete runtime context contract here.
        connection = super().connect()
        connection.execute(
            "SELECT set_config('gaialab.tenant_id', %s, true)",
            (effective_tenant or "",),
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
