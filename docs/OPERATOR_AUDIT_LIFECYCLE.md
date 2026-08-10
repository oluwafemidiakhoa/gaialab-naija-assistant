# GaiaLab Operator Security and Audit Lifecycle

This layer separates tenant service credentials from platform operator/admin credentials and records audit-export lifecycle actions as append-only events.

## Identity separation

Tenant service keys use:

```text
X-API-Key: gaia_live_...
```

They may receive service scopes such as:

- `verification:write`
- `receipts:read`
- `audit:export`

Operator/admin keys use a separate prefix, registry, header, and scope namespace:

```text
X-Admin-API-Key: gaia_admin_...
```

Supported admin scopes include:

- `audit:lifecycle`
- `tenants:manage`
- `policies:manage`
- `signing-keys:manage`

A tenant service key cannot authenticate to admin lifecycle endpoints.

## Provision an operator

```bash
python scripts/manage_trust_identity.py create-operator \
  --db data/trust_operators.sqlite3 \
  --name "Risk Administrator"
```

Issue an audit-lifecycle admin key:

```bash
python scripts/manage_trust_identity.py issue-admin-key \
  --db data/trust_operators.sqlite3 \
  --operator-id OPERATOR_ID \
  --scope audit:lifecycle
```

Store the returned admin key securely. Only its SHA-256 hash is persisted.

Configure the API:

```bash
export GAIALAB_OPERATOR_DB="data/trust_operators.sqlite3"
export GAIALAB_AUDIT_LIFECYCLE_DB="data/audit_lifecycle.sqlite3"
```

## Export lifecycle

A tenant service key with `audit:export` may create an evidence package:

```text
POST /v1/audit/exports
```

The request may include `retention_until`. If lifecycle storage is configured, Gaia registers immutable package metadata and records an `export_registered` event linked to the service key that created it.

Lifecycle state is derived from append-only events rather than silently overwriting history.

Supported lifecycle events include:

- `legal_hold_placed`
- `legal_hold_released`
- `retention_extended`
- `reviewed`
- `exported`
- `retention_eligible`

Admin-only endpoints:

```text
GET  /v1/admin/audit/exports/{package_id}
GET  /v1/admin/audit/exports/{package_id}/retention
POST /v1/admin/audit/exports/{package_id}/events
```

All require:

```text
X-Admin-API-Key: gaia_admin_...
```

with `audit:lifecycle` scope.

## Retention and legal holds

`retention_status` reports:

- configured retention deadline
- whether that deadline has expired
- whether a legal hold is active
- whether the package is eligible for deletion

An expired package is **not** eligible for deletion while a legal hold is active.

This implementation records eligibility only. It deliberately does not automatically delete audit packages or receipts. Destructive retention enforcement should remain a separate, explicitly authorized workflow with managed-storage controls and backup policy.

## Security boundary

Operator authentication is not a replacement for tenant API keys. The two credential types have separate purposes:

- tenant service keys operate within one tenant's verification/receipt/audit-export boundary
- admin keys govern platform-level lifecycle and administrative actions

Admin credentials should be managed in a dedicated secret store, rotated independently, and granted least-privilege scopes.

## Current storage model

The local MVP uses SQLite. Production deployment should move operator identities, lifecycle events, receipts, and rate limits to managed transactional infrastructure with strong backup, encryption, replication, and database-level tenant/access policies.
