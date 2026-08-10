"""RLS-enforcing Neon store wrappers.

Each protected database operation establishes its own context immediately around
the query path. This avoids relying on request-thread ContextVar propagation.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Mapping, Sequence

from src.neon_rls import clear_rls_context, current_rls_context, set_operator_context, set_tenant_context
from src.neon_storage import NeonAuditLifecycleStore, NeonReceiptStore, NeonTenantPolicyStore


@contextmanager
def _tenant_scope(tenant_id: str):
    previous = current_rls_context()
    set_tenant_context(tenant_id)
    try:
        yield
    finally:
        clear_rls_context()
        if previous["operator_mode"]:
            set_operator_context()
        elif previous["tenant_id"]:
            set_tenant_context(previous["tenant_id"])


@contextmanager
def _operator_scope():
    previous = current_rls_context()
    set_operator_context()
    try:
        yield
    finally:
        clear_rls_context()
        if previous["operator_mode"]:
            set_operator_context()
        elif previous["tenant_id"]:
            set_tenant_context(previous["tenant_id"])


class RLSNeonReceiptStore(NeonReceiptStore):
    def save(
        self,
        verification_id: str,
        envelope: Mapping[str, Any],
        *,
        tenant_id: str | None = None,
    ) -> bool:
        if tenant_id is None:
            raise ValueError("Neon RLS receipt persistence requires tenant_id")
        with _tenant_scope(tenant_id):
            return super().save(verification_id, envelope, tenant_id=tenant_id)

    def get(self, verification_id: str, *, tenant_id: str | None = None) -> dict[str, Any] | None:
        if tenant_id is None:
            raise ValueError("Neon RLS receipt lookup requires tenant_id")
        with _tenant_scope(tenant_id):
            return super().get(verification_id, tenant_id=tenant_id)

    def list_for_tenant(
        self,
        tenant_id: str,
        *,
        created_from: str | None = None,
        created_to: str | None = None,
        limit: int = 10000,
    ) -> list[dict[str, Any]]:
        with _tenant_scope(tenant_id):
            return super().list_for_tenant(
                tenant_id,
                created_from=created_from,
                created_to=created_to,
                limit=limit,
            )


class RLSNeonTenantPolicyStore(NeonTenantPolicyStore):
    def create_version(
        self,
        tenant_id: str,
        policy: Mapping[str, Any],
        *,
        activate: bool = True,
        note: str | None = None,
    ) -> dict[str, Any]:
        with _tenant_scope(tenant_id):
            return super().create_version(tenant_id, policy, activate=activate, note=note)

    def activate(
        self,
        tenant_id: str,
        policy_id: str,
        *,
        note: str | None = None,
    ) -> dict[str, Any]:
        with _tenant_scope(tenant_id):
            return super().activate(tenant_id, policy_id, note=note)

    def active_for(self, tenant_id: str) -> dict[str, Any]:
        with _tenant_scope(tenant_id):
            return super().active_for(tenant_id)

    def list_versions(self, tenant_id: str) -> list[dict[str, Any]]:
        with _tenant_scope(tenant_id):
            return super().list_versions(tenant_id)

    def get_for_tenant(self, tenant_id: str, policy_id: str) -> dict[str, Any] | None:
        with _tenant_scope(tenant_id):
            record = super().get(policy_id)
            if record is None or record["tenant_id"] != tenant_id:
                return None
            return record


class RLSNeonAuditLifecycleStore(NeonAuditLifecycleStore):
    def register_export(
        self,
        package: Mapping[str, Any],
        *,
        tenant_id: str,
        created_by_key_id: str | None,
        retention_until: str | None = None,
    ) -> dict[str, Any]:
        with _tenant_scope(tenant_id):
            return super().register_export(
                package,
                tenant_id=tenant_id,
                created_by_key_id=created_by_key_id,
                retention_until=retention_until,
            )

    def get(self, package_id: str) -> dict[str, Any] | None:
        with _operator_scope():
            return super().get(package_id)

    def events(self, package_id: str) -> list[dict[str, Any]]:
        with _operator_scope():
            return super().events(package_id)

    def add_event(
        self,
        package_id: str,
        *,
        actor_type: str,
        actor_id: str | None,
        event_type: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if actor_type != "operator":
            raise PermissionError("RLS lifecycle mutations require operator context")
        with _operator_scope():
            return super().add_event(
                package_id,
                actor_type=actor_type,
                actor_id=actor_id,
                event_type=event_type,
                metadata=metadata,
            )

    def retention_status(self, package_id: str, *, now=None) -> dict[str, Any]:
        with _operator_scope():
            return super().retention_status(package_id, now=now)
