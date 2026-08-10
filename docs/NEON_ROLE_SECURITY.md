# Neon database-role security

GaiaLab Trust Rail uses separate PostgreSQL identities for schema administration, tenant runtime traffic, and operator/admin runtime traffic.

## Required identities

### Migration identity

`GAIALAB_MIGRATION_DATABASE_URL`

Use a Neon owner or migration-capable role only for:

- applying `migrations/neon/*.sql`
- creating or rotating runtime database roles
- tenant/operator/API-key provisioning
- tenant policy administration
- signing-key registration and lifecycle administration

Do not use this credential as the normal API runtime connection.

### Tenant runtime identity

`GAIALAB_DATABASE_URL`

Use the `gaialab_runtime` login (or another role registered as `tenant_runtime`) for normal tenant API traffic.

It is explicitly created with:

```text
NOSUPERUSER
NOBYPASSRLS
NOCREATEDB
NOCREATEROLE
NOINHERIT
```

Its table privileges are limited to authentication reads and the DML required for verification, rate limiting, receipt persistence, and tenant audit-export registration.

### Operator runtime identity

`GAIALAB_OPERATOR_DATABASE_URL`

Use the `gaialab_operator` login (or another role registered as `operator_runtime`) for admin audit-lifecycle endpoints.

It is also created with:

```text
NOSUPERUSER
NOBYPASSRLS
NOCREATEDB
NOCREATEROLE
NOINHERIT
```

Its access is limited to operator authentication plus audit-export/lifecycle reads and mutations.

The API never falls back from the operator URL to the tenant runtime URL. Admin routes fail closed when `GAIALAB_OPERATOR_DATABASE_URL` is absent.

## Why operator access is tied to the DB login

The first RLS implementation used a custom session setting to represent operator mode. Custom PostgreSQL settings are client-controlled, so they are not a suitable authorization boundary.

Migration `0003_database_roles.sql` replaces that mechanism with `gaialab_is_operator()`, which checks `SESSION_USER` against the protected `gaialab_database_roles` registry.

Tenant runtime code can still set `gaialab.tenant_id` because that setting only narrows access to a tenant ID. It cannot turn itself into an operator.

## Bootstrap order

1. Create a Neon database/branch for the environment.
2. Set `GAIALAB_MIGRATION_DATABASE_URL` to the owner/direct connection.
3. Apply migrations:

```bash
python scripts/init_neon_storage.py
```

4. Generate strong, unique passwords outside the repository and export:

```bash
export GAIALAB_RUNTIME_ROLE_PASSWORD='...'
export GAIALAB_OPERATOR_ROLE_PASSWORD='...'
```

5. Optionally override the role names:

```bash
export GAIALAB_RUNTIME_ROLE='gaialab_runtime'
export GAIALAB_OPERATOR_ROLE='gaialab_operator'
```

6. Configure and verify the roles:

```bash
python scripts/configure_neon_roles.py
```

7. Create pooled Neon connection strings for those two roles and set:

```bash
export GAIALAB_DATABASE_URL='postgresql://gaialab_runtime:...@.../neondb?sslmode=require'
export GAIALAB_OPERATOR_DATABASE_URL='postgresql://gaialab_operator:...@.../neondb?sslmode=require'
```

8. Use `GAIALAB_MIGRATION_DATABASE_URL` for provisioning commands:

```bash
python scripts/manage_neon_trust.py create-tenant --name 'Example Fintech'
```

9. Remove the migration credential from the API runtime environment if the deployment platform permits separate migration and runtime jobs.

## CI secrets

The workflow `.github/workflows/neon-trust-ci.yml` always runs static Neon contract tests.

For live integration testing, configure a disposable/test Neon branch with these repository secrets:

- `NEON_TEST_MIGRATION_DATABASE_URL`
- `NEON_TEST_RUNTIME_DATABASE_URL`
- `NEON_TEST_OPERATOR_DATABASE_URL`

The live test verifies:

- all migrations are applied with no checksum drift
- runtime/operator roles are login roles but not superuser, `CREATEROLE`, `CREATEDB`, or `BYPASSRLS`
- one tenant cannot read another tenant's protected receipt or audit-export rows
- RLS blocks a cross-tenant insert
- the registered operator DB login can read and append audit lifecycle evidence

Do not point live CI tests at the production branch/database.

## Secret handling

Database URLs and role passwords are deployment secrets. They must never be committed, included in migration SQL, copied into fixtures, or printed in application logs.

If a database URL containing a password is shared in chat, an issue, a build log, or another non-secret channel, rotate that credential before production use.
