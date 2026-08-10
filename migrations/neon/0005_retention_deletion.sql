-- GaiaLab Naija Trust Rail / destructive retention authorization
-- Migration: 0005_retention_deletion
--
-- Deletion plans and approvals deliberately do not reference audit_exports with
-- a foreign key so the authorization evidence survives deletion of the export.

CREATE TABLE IF NOT EXISTS retention_deletion_plans (
    plan_id TEXT PRIMARY KEY,
    package_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    manifest_sha256 TEXT NOT NULL,
    eligibility_snapshot_sha256 TEXT NOT NULL,
    eligibility_snapshot_json TEXT NOT NULL,
    evidence_signature_json TEXT NOT NULL,
    created_by_operator_id TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_retention_deletion_plans_package
    ON retention_deletion_plans(package_id, created_at);

CREATE TABLE IF NOT EXISTS retention_deletion_events (
    event_id BIGSERIAL PRIMARY KEY,
    plan_id TEXT NOT NULL REFERENCES retention_deletion_plans(plan_id),
    actor_operator_id TEXT NOT NULL,
    event_type TEXT NOT NULL CHECK (event_type IN ('approved', 'cancelled', 'executed')),
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_retention_deletion_events_plan
    ON retention_deletion_events(plan_id, event_id);

CREATE UNIQUE INDEX IF NOT EXISTS idx_retention_deletion_one_approval_per_operator
    ON retention_deletion_events(plan_id, actor_operator_id)
    WHERE event_type = 'approved';

CREATE UNIQUE INDEX IF NOT EXISTS idx_retention_deletion_single_cancel
    ON retention_deletion_events(plan_id)
    WHERE event_type = 'cancelled';

CREATE UNIQUE INDEX IF NOT EXISTS idx_retention_deletion_single_execute
    ON retention_deletion_events(plan_id)
    WHERE event_type = 'executed';

REVOKE ALL ON TABLE retention_deletion_plans FROM PUBLIC;
REVOKE ALL ON TABLE retention_deletion_events FROM PUBLIC;
