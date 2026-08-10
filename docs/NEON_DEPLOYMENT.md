# GaiaLab Trust Rail on Neon Postgres

Neon Postgres is the production persistence target for the GaiaLab Naija Trust Rail. SQLite remains supported for local development and isolated tests.

## Storage selection

The API automatically selects Neon when this variable is present:

```bash
export GAIALAB_DATABASE_URL="postgresql://..."
```

Use the pooled Neon connection string for `GAIALAB_DATABASE_URL`. It is used by normal API traffic for tenant authentication, operator authentication, policies, rate limiting, receipts, signing-key lifecycle, audit exports, and audit lifecycle events.

For migrations, prefer a direct Neon connection string:

```bash
export GAIALAB_MIGRATION_DATABASE_URL="postgresql://..."
```

If `GAIALAB_MIGRATION_DATABASE_URL` is omitted, migration tooling falls back to `GAIALAB_DATABASE_URL`.

Private database URLs are secrets and must never be committed to the repository.

## Versioned migrations

API startup does **not** create or modify database schema. `NeonBackend` construction is intentionally side-effect free.

Schema changes live in ordered SQL files under:

```text
migrations/neon/
```

Current migrations:

- `0001_initial.sql` — Trust Rail schema baseline
- `0002_tenant_rls.sql` — tenant Row Level Security policies

Apply migrations before deploying a new application revision:

```bash
python scripts/init_neon_storage.py
```

The migration runner records applied versions and SHA-256 checksums in `gaialab_schema_migrations`. If an already-applied migration file changes, deployment fails with migration drift instead of silently changing history.

Applied migration files are immutable. Add a new numbered migration for every future schema change.

## Row Level Security

The tenant data plane uses PostgreSQL Row Level Security as defense in depth in addition to application-level tenant checks.

RLS is enabled and forced on:

- `verification_receipts`
- `tenant_policy_versions`
- `tenant_policy_events`
- `audit_exports`
- `audit_export_events`

Tenant transactions set a transaction-local context value:

```text
gaialab.tenant_id = <authenticated tenant id>
```

Protected policies compare each row's tenant ownership against that value. A connection with no tenant context receives no tenant data from those tables.

Operator-only platform transactions set:

```text
gaialab.operator_mode = on
```

This is used only by trusted server-side control-plane operations such as audit lifecycle administration. Tenant service credentials never set operator mode.

`FORCE ROW LEVEL SECURITY` is used so table ownership alone does not disable the policy. The production runtime database role must also **not** have PostgreSQL `BYPASSRLS` or superuser privileges. Migration credentials may be more privileged, but they should not be used as the application runtime credential.

## Shared tables

The Neon schema includes:

- `tenants`
- `tenant_api_keys`
- `operators`
- `operator_api_keys`
- `signing_keys`
- `signing_key_events`
- `tenant_policy_versions`
- `tenant_policy_events`
- `verification_receipts`
- `api_rate_windows`
- `audit_exports`
- `audit_export_events`
- `gaialab_schema_migrations`

Identity, signing-key, and rate-limit tables remain server-internal control-plane tables and are not exposed as tenant-query surfaces. Application authorization still applies to all routes.

## Provision a tenant

```bash
python scripts/manage_neon_trust.py create-tenant \
  --name "Example Fintech"
```

Issue a verification key:

```bash
python scripts/manage_neon_trust.py issue-api-key \
  --tenant-id TENANT_ID \
  --scope verification:write \
  --scope receipts:read \
  --rate-limit-per-minute 120
```

Issue a separate audit export key when needed:

```bash
python scripts/manage_neon_trust.py issue-api-key \
  --tenant-id TENANT_ID \
  --scope audit:export \
  --rate-limit-per-minute 20
```

The plaintext API key is returned only at issuance time. The database stores its SHA-256 hash.

## Provision an operator

```bash
python scripts/manage_neon_trust.py create-operator \
  --name "Risk Administrator"
```

Then issue a separate admin credential:

```bash
python scripts/manage_neon_trust.py issue-admin-key \
  --operator-id OPERATOR_ID \
  --scope audit:lifecycle
```

Tenant service credentials and operator credentials remain separate namespaces.

## Register the receipt signing key

Generate the Ed25519 keypair with the existing generator:

```bash
python scripts/generate_trust_signing_key.py
```

Keep the private key in your deployment secret store:

```bash
export GAIALAB_TRUST_SIGNING_KEY_B64="..."
```

Register only the public key in Neon:

```bash
python scripts/manage_neon_trust.py register-signing-key \
  --public-key-b64 "PUBLIC_KEY_B64" \
  --label "production-2026-01"
```

The active public-key lifecycle remains append-only (`registered`, `activated`, `retired`, `revoked`).

## Configure a tenant policy

```bash
python scripts/manage_neon_trust.py create-policy \
  --tenant-id TENANT_ID \
  --file config/trust_policies/example_fintech_strict.json \
  --note "Initial production controls"
```

Policy versions are immutable. Activation is an append-only event and the active policy ID/hash is bound into every verification receipt.

## Run the API

```bash
uvicorn src.trust_api:app --host 0.0.0.0 --port 8000
```

`GET /health` reports `storage_mode: neon` when the Neon backend is active.

## Runtime behavior

When `GAIALAB_DATABASE_URL` is configured, the same API routes use Neon for:

```text
X-API-Key authentication
        ↓
transaction-local tenant context
        ↓
Postgres RLS boundary
        ↓
per-key rate-limit row lock
        ↓
tenant policy lookup
        ↓
verification
        ↓
receipt persistence
        ↓
audit export
        ↓
audit lifecycle / legal hold
```

The Postgres rate limiter uses a row-level lock (`SELECT ... FOR UPDATE`) for each key/window so concurrent instances share one counter.

Receipt insertion checks an existing verification ID inside the same transaction before inserting, preserving write-once tenant ownership semantics. RLS independently prevents a tenant-scoped transaction from reading or inserting another tenant's protected rows.

## Deployment order

A production deployment should follow this order:

1. create or update the Neon database/runtime roles
2. set the direct migration URL in the deployment environment
3. run `python scripts/init_neon_storage.py`
4. confirm there are no pending/drifted migrations
5. deploy the API using the pooled runtime URL
6. run health and tenant-isolation smoke tests
7. remove migration credentials from the runtime service if they are not needed after deployment

Never use a superuser or `BYPASSRLS` role as the normal API runtime identity.

## Local fallback

If `GAIALAB_DATABASE_URL` is absent, the existing SQLite environment variables continue to work:

- `GAIALAB_TENANT_DB`
- `GAIALAB_OPERATOR_DB`
- `GAIALAB_TENANT_POLICY_DB`
- `GAIALAB_RATE_LIMIT_DB`
- `GAIALAB_TRUST_KEY_REGISTRY_DB`
- `GAIALAB_TRUST_RECEIPT_DB`
- `GAIALAB_AUDIT_LIFECYCLE_DB`

This keeps the current test and local-development workflow intact while Neon is the production persistence layer.

## Current boundary

This slice adds versioned migration discipline and database-level tenant isolation. It does not yet include:

- automated backup/restore drills
- connection/transaction telemetry
- read replicas or analytics replicas
- destructive retention execution
- live Neon RLS integration tests in repository CI

Those should be added as later production-hardening slices rather than mixed into trust-policy logic.
