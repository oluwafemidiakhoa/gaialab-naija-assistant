-- GaiaLab Naija Trust Rail / Neon schema baseline
-- Migration: 0001_initial

CREATE TABLE IF NOT EXISTS tenants (
    tenant_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tenant_api_keys (
    key_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES tenants(tenant_id),
    key_hash TEXT NOT NULL UNIQUE,
    label TEXT,
    scopes_json TEXT NOT NULL,
    rate_limit_per_minute INTEGER NOT NULL DEFAULT 120,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    disabled_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_tenant_api_keys_tenant
    ON tenant_api_keys(tenant_id, status);

CREATE TABLE IF NOT EXISTS operators (
    operator_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS operator_api_keys (
    key_id TEXT PRIMARY KEY,
    operator_id TEXT NOT NULL REFERENCES operators(operator_id),
    key_hash TEXT NOT NULL UNIQUE,
    label TEXT,
    scopes_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    disabled_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_operator_keys_operator
    ON operator_api_keys(operator_id, status);

CREATE TABLE IF NOT EXISTS signing_keys (
    key_id TEXT PRIMARY KEY,
    public_key_b64 TEXT NOT NULL,
    algorithm TEXT NOT NULL,
    label TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS signing_key_events (
    event_id BIGSERIAL PRIMARY KEY,
    key_id TEXT NOT NULL REFERENCES signing_keys(key_id),
    event_type TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_signing_key_events_key
    ON signing_key_events(key_id, event_id);

CREATE TABLE IF NOT EXISTS tenant_policy_versions (
    policy_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    policy_hash TEXT NOT NULL,
    policy_json TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(tenant_id, policy_hash)
);

CREATE TABLE IF NOT EXISTS tenant_policy_events (
    event_id BIGSERIAL PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    policy_id TEXT NOT NULL REFERENCES tenant_policy_versions(policy_id),
    event_type TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_tenant_policy_events
    ON tenant_policy_events(tenant_id, event_id);

CREATE TABLE IF NOT EXISTS verification_receipts (
    verification_id TEXT PRIMARY KEY,
    payload_sha256 TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    tenant_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_verification_receipts_tenant
    ON verification_receipts(tenant_id, created_at);

CREATE TABLE IF NOT EXISTS api_rate_windows (
    key_id TEXT NOT NULL,
    bucket_start BIGINT NOT NULL,
    count INTEGER NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(key_id, bucket_start)
);

CREATE TABLE IF NOT EXISTS audit_exports (
    package_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    manifest_sha256 TEXT NOT NULL,
    manifest_json TEXT NOT NULL,
    retention_until TIMESTAMPTZ,
    created_by_key_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_audit_exports_tenant
    ON audit_exports(tenant_id, created_at);

CREATE TABLE IF NOT EXISTS audit_export_events (
    event_id BIGSERIAL PRIMARY KEY,
    package_id TEXT NOT NULL REFERENCES audit_exports(package_id),
    actor_type TEXT NOT NULL,
    actor_id TEXT,
    event_type TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_audit_export_events
    ON audit_export_events(package_id, event_id);
