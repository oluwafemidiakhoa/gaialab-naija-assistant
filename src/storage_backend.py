"""Runtime storage selection for GaiaLab Naija Trust Rail.

Production Neon uses distinct tenant-runtime and operator-runtime database
connections. SQLite remains available for local development and isolated tests.
"""

from __future__ import annotations

from functools import lru_cache
import os
from typing import Any

from src.audit_lifecycle import AuditLifecycleStore
from src.key_registry import SigningKeyRegistry
from src.neon_rls import RLSNeonBackend, RLSNeonTenantRegistry
from src.neon_rls_storage import (
    RLSNeonAuditLifecycleStore,
    RLSNeonReceiptStore,
    RLSNeonTenantPolicyStore,
)
from src.neon_storage import (
    NeonAuditLifecycleStore,
    NeonOperatorRegistry,
    NeonRateLimiter,
    NeonSigningKeyRegistry,
)
from src.operator_auth import OperatorRegistry
from src.rate_limit import FixedWindowRateLimiter
from src.receipt_store import ReceiptStore
from src.tenant_auth import TenantRegistry
from src.tenant_policy import TenantPolicyStore


def _migration_url() -> str | None:
    return os.getenv("GAIALAB_MIGRATION_DATABASE_URL")


@lru_cache(maxsize=1)
def neon_backend() -> RLSNeonBackend | None:
    """Tenant-runtime backend using the least-privilege application role."""
    database_url = os.getenv("GAIALAB_DATABASE_URL")
    if not database_url:
        return None
    backend = RLSNeonBackend(
        database_url,
        migration_database_url=_migration_url() or database_url,
    )
    backend.assert_schema_current()
    return backend


@lru_cache(maxsize=1)
def operator_neon_backend() -> RLSNeonBackend | None:
    """Separate operator backend; never fall back to the tenant runtime URL."""
    database_url = os.getenv("GAIALAB_OPERATOR_DATABASE_URL")
    if not database_url:
        return None
    backend = RLSNeonBackend(
        database_url,
        migration_database_url=_migration_url() or database_url,
    )
    backend.assert_schema_current()
    return backend


def storage_mode() -> str:
    return "neon" if neon_backend() is not None else "sqlite"


def tenant_registry() -> Any:
    backend = neon_backend()
    if backend:
        return RLSNeonTenantRegistry(backend)
    path = os.getenv("GAIALAB_TENANT_DB")
    if not path:
        raise RuntimeError("tenant authentication is not configured")
    return TenantRegistry(path)


def operator_registry() -> Any:
    if neon_backend() is not None:
        backend = operator_neon_backend()
        if backend is None:
            raise RuntimeError("Neon operator authentication requires GAIALAB_OPERATOR_DATABASE_URL")
        return NeonOperatorRegistry(backend)
    path = os.getenv("GAIALAB_OPERATOR_DB")
    if not path:
        raise RuntimeError("operator authentication is not configured")
    return OperatorRegistry(path)


def signing_key_registry(*, required: bool = False) -> Any | None:
    backend = neon_backend()
    if backend:
        return NeonSigningKeyRegistry(backend)
    path = os.getenv("GAIALAB_TRUST_KEY_REGISTRY_DB")
    if not path:
        if required:
            raise RuntimeError("signing key registry is not configured")
        return None
    return SigningKeyRegistry(path)


def tenant_policy_store(*, required: bool = False) -> Any | None:
    backend = neon_backend()
    if backend:
        return RLSNeonTenantPolicyStore(backend)
    path = os.getenv("GAIALAB_TENANT_POLICY_DB")
    if not path:
        if required:
            raise RuntimeError("tenant policy store is not configured")
        return None
    return TenantPolicyStore(path)


def receipt_store(*, required: bool = True) -> Any | None:
    backend = neon_backend()
    if backend:
        return RLSNeonReceiptStore(backend)
    path = os.getenv("GAIALAB_TRUST_RECEIPT_DB")
    if not path:
        if required:
            raise RuntimeError("receipt persistence is not configured")
        return None
    return ReceiptStore(path)


def rate_limiter() -> Any:
    backend = neon_backend()
    if backend:
        return NeonRateLimiter(backend)
    path = os.getenv("GAIALAB_RATE_LIMIT_DB")
    if not path:
        tenant_db = os.getenv("GAIALAB_TENANT_DB")
        if not tenant_db:
            raise RuntimeError("rate limiting is not configured")
        path = tenant_db + ".rate.sqlite3"
    return FixedWindowRateLimiter(path)


def audit_lifecycle_store(*, required: bool = True, operator: bool = False) -> Any | None:
    tenant_backend = neon_backend()
    if tenant_backend:
        if operator:
            backend = operator_neon_backend()
            if backend is None:
                if required:
                    raise RuntimeError("Neon operator lifecycle access requires GAIALAB_OPERATOR_DATABASE_URL")
                return None
            return NeonAuditLifecycleStore(backend)
        return RLSNeonAuditLifecycleStore(tenant_backend)
    path = os.getenv("GAIALAB_AUDIT_LIFECYCLE_DB")
    if not path:
        if required:
            raise RuntimeError("audit lifecycle registry is not configured")
        return None
    return AuditLifecycleStore(path)
