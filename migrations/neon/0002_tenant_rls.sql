-- GaiaLab Naija Trust Rail / tenant Row Level Security
-- Migration: 0002_tenant_rls
--
-- Application transactions set gaialab.tenant_id for tenant service operations.
-- Operator-only transactions set gaialab.operator_mode = 'on'.
-- Empty context is fail-closed for protected tenant data-plane tables.

ALTER TABLE verification_receipts ENABLE ROW LEVEL SECURITY;
ALTER TABLE verification_receipts FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS gaialab_receipts_tenant_isolation ON verification_receipts;
CREATE POLICY gaialab_receipts_tenant_isolation ON verification_receipts
    USING (
        current_setting('gaialab.operator_mode', true) = 'on'
        OR tenant_id = nullif(current_setting('gaialab.tenant_id', true), '')
    )
    WITH CHECK (
        current_setting('gaialab.operator_mode', true) = 'on'
        OR tenant_id = nullif(current_setting('gaialab.tenant_id', true), '')
    );

ALTER TABLE tenant_policy_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE tenant_policy_versions FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS gaialab_policy_versions_tenant_isolation ON tenant_policy_versions;
CREATE POLICY gaialab_policy_versions_tenant_isolation ON tenant_policy_versions
    USING (
        current_setting('gaialab.operator_mode', true) = 'on'
        OR tenant_id = nullif(current_setting('gaialab.tenant_id', true), '')
    )
    WITH CHECK (
        current_setting('gaialab.operator_mode', true) = 'on'
        OR tenant_id = nullif(current_setting('gaialab.tenant_id', true), '')
    );

ALTER TABLE tenant_policy_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE tenant_policy_events FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS gaialab_policy_events_tenant_isolation ON tenant_policy_events;
CREATE POLICY gaialab_policy_events_tenant_isolation ON tenant_policy_events
    USING (
        current_setting('gaialab.operator_mode', true) = 'on'
        OR tenant_id = nullif(current_setting('gaialab.tenant_id', true), '')
    )
    WITH CHECK (
        current_setting('gaialab.operator_mode', true) = 'on'
        OR tenant_id = nullif(current_setting('gaialab.tenant_id', true), '')
    );

ALTER TABLE audit_exports ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_exports FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS gaialab_audit_exports_tenant_isolation ON audit_exports;
CREATE POLICY gaialab_audit_exports_tenant_isolation ON audit_exports
    USING (
        current_setting('gaialab.operator_mode', true) = 'on'
        OR tenant_id = nullif(current_setting('gaialab.tenant_id', true), '')
    )
    WITH CHECK (
        current_setting('gaialab.operator_mode', true) = 'on'
        OR tenant_id = nullif(current_setting('gaialab.tenant_id', true), '')
    );

ALTER TABLE audit_export_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_export_events FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS gaialab_audit_events_tenant_isolation ON audit_export_events;
CREATE POLICY gaialab_audit_events_tenant_isolation ON audit_export_events
    USING (
        current_setting('gaialab.operator_mode', true) = 'on'
        OR EXISTS (
            SELECT 1
            FROM audit_exports AS parent
            WHERE parent.package_id = audit_export_events.package_id
              AND parent.tenant_id = nullif(current_setting('gaialab.tenant_id', true), '')
        )
    )
    WITH CHECK (
        current_setting('gaialab.operator_mode', true) = 'on'
        OR EXISTS (
            SELECT 1
            FROM audit_exports AS parent
            WHERE parent.package_id = audit_export_events.package_id
              AND parent.tenant_id = nullif(current_setting('gaialab.tenant_id', true), '')
        )
    );
