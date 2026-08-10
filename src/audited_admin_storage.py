"""Audited wrappers for privileged operator storage mutations.

A requested action is appended before the mutation and a completed action after
success. If the underlying mutation fails, the requested action remains as an
auditable attempted privileged operation.
"""

from __future__ import annotations

from typing import Any, Mapping


class AuditedAuditLifecycleStore:
    def __init__(self, store: Any, action_log: Any):
        self.store = store
        self.action_log = action_log

    def __getattr__(self, name: str):
        return getattr(self.store, name)

    def add_event(
        self,
        package_id: str,
        *,
        actor_type: str,
        actor_id: str | None,
        event_type: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if actor_type != "operator" or not actor_id:
            return self.store.add_event(
                package_id,
                actor_type=actor_type,
                actor_id=actor_id,
                event_type=event_type,
                metadata=metadata,
            )
        safe_metadata = {"event_type": event_type}
        self.action_log.append(
            operator_id=actor_id,
            key_id=None,
            action_type=f"audit.lifecycle.{event_type}.requested",
            target_type="audit_export",
            target_id=package_id,
            metadata=safe_metadata,
        )
        result = self.store.add_event(
            package_id,
            actor_type=actor_type,
            actor_id=actor_id,
            event_type=event_type,
            metadata=metadata,
        )
        self.action_log.append(
            operator_id=actor_id,
            key_id=None,
            action_type=f"audit.lifecycle.{event_type}.completed",
            target_type="audit_export",
            target_id=package_id,
            metadata=safe_metadata,
        )
        return result


class AuditedRetentionDeletionStore:
    def __init__(self, store: Any, action_log: Any):
        self.store = store
        self.action_log = action_log

    def __getattr__(self, name: str):
        return getattr(self.store, name)

    def _record(self, *, operator_id: str, action: str, phase: str, plan_id: str, metadata=None) -> None:
        self.action_log.append(
            operator_id=operator_id,
            key_id=None,
            action_type=f"retention.{action}.{phase}",
            target_type="deletion_plan",
            target_id=plan_id,
            metadata=dict(metadata or {}),
        )

    def create_plan(
        self,
        *,
        snapshot: Mapping[str, Any],
        evidence_signature: Mapping[str, Any],
        created_by_operator_id: str,
    ) -> dict[str, Any]:
        # The final plan id is deterministic from the snapshot, but the wrapper
        # does not need to reproduce its derivation. The package id is hashed by
        # the action ledger and used as the pre-creation target.
        package_id = str(snapshot["package_id"])
        self.action_log.append(
            operator_id=created_by_operator_id,
            key_id=None,
            action_type="retention.plan.requested",
            target_type="audit_export",
            target_id=package_id,
            metadata={"eligible_for_deletion": bool(snapshot.get("eligible_for_deletion"))},
        )
        result = self.store.create_plan(
            snapshot=snapshot,
            evidence_signature=evidence_signature,
            created_by_operator_id=created_by_operator_id,
        )
        self._record(
            operator_id=created_by_operator_id,
            action="plan",
            phase="completed",
            plan_id=result["plan_id"],
            metadata={"approval_count": result.get("approval_count", 0)},
        )
        return result

    def approve(self, plan_id: str, operator_id: str) -> dict[str, Any]:
        self._record(operator_id=operator_id, action="approval", phase="requested", plan_id=plan_id)
        result = self.store.approve(plan_id, operator_id)
        self._record(
            operator_id=operator_id,
            action="approval",
            phase="completed",
            plan_id=plan_id,
            metadata={"approval_count": result.get("approval_count", 0)},
        )
        return result

    def cancel(self, plan_id: str, operator_id: str, *, reason: str | None = None) -> dict[str, Any]:
        self._record(operator_id=operator_id, action="cancel", phase="requested", plan_id=plan_id)
        result = self.store.cancel(plan_id, operator_id, reason=reason)
        self._record(operator_id=operator_id, action="cancel", phase="completed", plan_id=plan_id)
        return result

    def execute(self, plan_id: str, operator_id: str, *, now=None) -> dict[str, Any]:
        self._record(operator_id=operator_id, action="execute", phase="requested", plan_id=plan_id)
        result = self.store.execute(plan_id, operator_id, now=now)
        executed = [event for event in result.get("events", []) if event.get("event_type") == "executed"]
        deletion_metadata = dict(executed[-1].get("metadata") or {}) if executed else {}
        self._record(
            operator_id=operator_id,
            action="execute",
            phase="completed",
            plan_id=plan_id,
            metadata=deletion_metadata,
        )
        return result
