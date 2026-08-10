"""Runtime storage selection for GaiaLab Naija Trust Rail.

If GAIALAB_DATABASE_URL is configured, all production persistence uses the shared
Neon Postgres backend with RLS-enforcing store wrappers. Otherwise existing
SQLite stores remain available for local development and tests.
"""

from __future__ import annotations

from functools import lru_cache
import os
from typing import Any

from src.audit_lifecycle import AuditLifecycleStore
from src.key_registry import SigningKeyRegistry
from src.neon_rls import RLSNeonBackend, RLSNeonOperatorRegistry, RLSNeonTenantRegistry
from src.neon_rls_storage import (
    RLSNeonAuditLifecycleStore,
    RLSNeonReceiptStore,
    RLSNeonTenantPolicyStore,
)
from src.neon_storage import NeonRateLimiter, NeonSigningKeyRegistry
from src.operator_auth import OperatorRegistry
from src.rate_limit import FixedWindowRateLimiter
from src.receipt_store import ReceiptStore
from src.tenant_auth import TenantRegistry
from src.tenant_policy import TenantPolicyStore


@lru_cache(maxsize=1)
def neon_backend() -> RLSNeonBackend | None:
    database_url = os.getenv("GAIALAB_DATABASE_URL")
    if not database_url:
        return None
    backend = RLSNeonBackend(
        database_url,
        migration_database_url=os.getenv("GAIALAB_MIGRATION_DATABASE_URL"),
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
    backend = neon_backend()
    if backend:
        return RLSNeonOperatorRegistry(backend)
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


def audit_lifecycle_store(*, required: bool = True) -> Any | None:
    backend = neon_backend()
    if backend:
        return RLSNeonAuditLifecycleStore(backend)
    path = os.getenv("GAIALAB_AUDIT_LIFECYCLE_DB")
    if not path:
        if required:
            raise RuntimeError("audit lifecycle registry is not configured")
        return None
    return AuditLifecycleStore(path)
