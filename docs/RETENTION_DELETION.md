# Destructive Retention Authorization

GaiaLab Naija Trust Rail treats destructive retention as a separate privileged workflow. Retention expiry alone never deletes evidence.

## Scope

The workflow deletes only the selected Audit Evidence Package registration and its lifecycle events:

- `audit_exports`: deleted for the approved package
- `audit_export_events`: deleted for the approved package
- `verification_receipts`: **never deleted by this workflow**
- `retention_deletion_plans` and `retention_deletion_events`: preserved as the authorization/evidence ledger

This boundary prevents deleting source verification receipts merely because one derived audit package reached its retention date.

## Preconditions

A deletion plan can be created only when all of the following are true:

1. the export exists;
2. its retention deadline has expired;
3. no legal hold is active;
4. `GAIALAB_TRUST_SIGNING_KEY_B64` is configured;
5. the signing key is active in the signing-key registry;
6. the caller is an operator with the explicit `audit:delete` scope.

The plan stores a signed eligibility snapshot containing the package ID, tenant ID, manifest hash, retention deadline, legal-hold state, lifecycle-event count, and a dry-run count of rows that would be deleted.

## Two-person authorization

Creating a plan does not authorize deletion. The plan needs approvals from **two distinct operator identities**. Repeating an approval with the same operator does not increase the approval count.

`audit:lifecycle` alone is insufficient. Deletion endpoints require `audit:delete`, allowing deletion credentials to be issued only to the operators responsible for destructive retention.

## Execution

Execution is fail-closed. In one database transaction the operator store:

1. locks the deletion plan;
2. verifies two distinct approvals;
3. rejects cancelled or already executed plans;
4. verifies the Ed25519 signature on the eligibility snapshot;
5. verifies package, tenant, and manifest bindings;
6. locks the target audit export;
7. replays the latest legal-hold lifecycle;
8. rechecks the retention deadline;
9. deletes the package lifecycle rows and export registration;
10. appends an `executed` event to the independent retention ledger.

If a legal hold is placed after planning but before execution, execution fails. If signed eligibility evidence is modified, execution fails.

## API sequence

All endpoints use `X-Admin-API-Key` and require `audit:delete`.

```text
POST /v1/admin/audit/exports/{package_id}/deletion-plans
GET  /v1/admin/audit/deletion-plans/{plan_id}
POST /v1/admin/audit/deletion-plans/{plan_id}/approvals
POST /v1/admin/audit/deletion-plans/{plan_id}/cancel
POST /v1/admin/audit/deletion-plans/{plan_id}/execute
```

Recommended operating sequence:

```text
Operator A creates plan
        |
        v
Inspect signed dry-run evidence
        |
        +--> Operator A or B approves
        |
        +--> Different operator approves
        |
        v
Recheck ready_to_execute = true
        |
        v
Authorized operator executes
```

## Neon privileges

The tenant runtime role has no access to the retention authorization tables and no DELETE privilege on audit export tables.

The separate operator runtime role receives narrowly scoped access to:

- read/insert retention plans and events;
- delete `audit_exports` and `audit_export_events`;
- no DELETE permission on `verification_receipts`.

The migration/owner credential remains responsible for schema migrations and role provisioning.

## Cancellation

A plan can be cancelled before execution. Cancellation is append-only and final for that plan. Operators must create a new plan, with a fresh signed eligibility snapshot, if deletion is reconsidered later.

## Evidence after deletion

The retained authorization ledger proves:

- which export was targeted;
- the manifest hash that was bound to the plan;
- the eligibility state observed before authorization;
- the signing key and signature over that snapshot;
- which distinct operators approved;
- which operator executed;
- how many audit-export and lifecycle rows were deleted;
- that verification receipts were outside the deletion scope.

It does **not** prove that upstream business evidence was truthful; it proves the integrity and authorization history of the retention action.
