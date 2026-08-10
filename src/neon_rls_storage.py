"""Tenant RLS-enforcing Neon store wrappers.

Protected tenant operations establish tenant context immediately around the
query path. Cross-tenant operator lifecycle access uses a separate database
login and the base Neon lifecycle store instead of a session-controlled bypass.
"""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
from typing import Any, Mapping

from src.neon_rls import clear_rls_context, current_rls_context, set_tenant_context
from src.neon_storage import NeonAuditLifecycleStore, NeonReceiptStore, NeonTenantPolicyStore
from src.receipt_store import ReceiptConflictError, _canonical_json as _receipt_json


@contextmanager
def _tenant_scope(tenant_id: str):
    previous = current_rls_context()
    set_tenant_context(tenant_id)
    try:
        yield
    finally:
        clear_rls_context()
        if previous["tenant_id"]:
            set_tenant_context(previous["tenant_id"])


class RLSNeonReceiptStore(NeonReceiptStore):
    def save(
        self,
        verification_id: str,
        envelope: Mapping[str, Any],
        *,
        tenant_id: str | None = None,
    ) -> bool:
        """Persist once atomically and verify idempotent retries by content hash.

        The base MVP implementation performed ``SELECT ... FOR UPDATE`` before
        inserting. A missing row cannot be locked, so concurrent first-writers
        could race on the primary key. The RLS production path instead lets the
        primary-key constraint arbitrate the first writer atomically.
        """
        if tenant_id is None:
            raise ValueError("Neon RLS receipt persistence requires tenant_id")
        payload_json = _receipt_json(envelope)
        payload_sha256 = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
        with _tenant_scope(tenant_id):
            with self.backend.connect(tenant_id=tenant_id) as connection:
                inserted = connection.execute(
                    "INSERT INTO verification_receipts "
                    "(verification_id,payload_sha256,payload_json,tenant_id) "
                    "VALUES (%s,%s,%s,%s) "
                    "ON CONFLICT (verification_id) DO NOTHING "
                    "RETURNING verification_id",
                    (verification_id, payload_sha256, payload_json, tenant_id),
                ).fetchone()
                if inserted is not None:
                    return True

                existing = connection.execute(
                    "SELECT payload_sha256,tenant_id FROM verification_receipts "
                    "WHERE verification_id=%s",
                    (verification_id,),
                ).fetchone()
                # A primary-key conflict with no RLS-visible row means the ID is
                # owned outside this tenant. Fail closed without disclosing who.
                if existing is None:
                    raise ReceiptConflictError(
                        f"verification_id {verification_id} already exists"
                    )
                if (
                    existing["payload_sha256"] != payload_sha256
                    or existing["tenant_id"] != tenant_id
                ):
                    raise ReceiptConflictError(
                        f"verification_id {verification_id} already exists with different content"
                    )
                return False

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
    """Tenant-side audit lifecycle access used when registering an export."""

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
