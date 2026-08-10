-- GaiaLab Naija Trust Rail / database-role hardening
-- Migration: 0003_database_roles
--
-- Removes the session-GUC operator bypass. Operator access is derived from the
-- authenticated PostgreSQL login (SESSION_USER) through a protected registry.

CREATE TABLE IF NOT EXISTS gaialab_database_roles (
    role_name TEXT PRIMARY KEY,
    role_kind TEXT NOT NULL CHECK (
        role_kind IN ('tenant_runtime', 'operator_runtime', 'migration')
    ),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

REVOKE ALL ON TABLE gaialab_database_roles FROM PUBLIC;

CREATE OR REPLACE FUNCTION gaialab_is_operator()
RETURNS BOOLEAN
LANGUAGE SQL
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
    SELECT EXISTS (
        SELECT 1
        FROM public.gaialab_database_roles
        WHERE role_name = SESSION_USER
          AND role_kind = 'operator_runtime'
    );
$$;

REVOKE ALL ON FUNCTION gaialab_is_operator() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION gaialab_is_operator() TO PUBLIC;

DROP POLICY IF EXISTS gaialab_receipts_tenant_isolation ON verification_receipts;
CREATE POLICY gaialab_receipts_tenant_isolation ON verification_receipts
    USING (
        gaialab_is_operator()
        OR tenant_id = nullif(current_setting('gaialab.tenant_id', true), '')
    )
    WITH CHECK (
        gaialab_is_operator()
        OR tenant_id = nullif(current_setting('gaialab.tenant_id', true), '')
    );

DROP POLICY IF EXISTS gaialab_policy_versions_tenant_isolation ON tenant_policy_versions;
CREATE POLICY gaialab_policy_versions_tenant_isolation ON tenant_policy_versions
    USING (
        gaialab_is_operator()
        OR tenant_id = nullif(current_setting('gaialab.tenant_id', true), '')
    )
    WITH CHECK (
        gaialab_is_operator()
        OR tenant_id = nullif(current_setting('gaialab.tenant_id', true), '')
    );

DROP POLICY IF EXISTS gaialab_policy_events_tenant_isolation ON tenant_policy_events;
CREATE POLICY gaialab_policy_events_tenant_isolation ON tenant_policy_events
    USING (
        gaialab_is_operator()
        OR tenant_id = nullif(current_setting('gaialab.tenant_id', true), '')
    )
    WITH CHECK (
        gaialab_is_operator()
        OR tenant_id = nullif(current_setting('gaialab.tenant_id', true), '')
    );

DROP POLICY IF EXISTS gaialab_audit_exports_tenant_isolation ON audit_exports;
CREATE POLICY gaialab_audit_exports_tenant_isolation ON audit_exports
    USING (
        gaialab_is_operator()
        OR tenant_id = nullif(current_setting('gaialab.tenant_id', true), '')
    )
    WITH CHECK (
        gaialab_is_operator()
        OR tenant_id = nullif(current_setting('gaialab.tenant_id', true), '')
    );

DROP POLICY IF EXISTS gaialab_audit_events_tenant_isolation ON audit_export_events;
CREATE POLICY gaialab_audit_events_tenant_isolation ON audit_export_events
    USING (
        gaialab_is_operator()
        OR EXISTS (
            SELECT 1
            FROM audit_exports AS parent
            WHERE parent.package_id = audit_export_events.package_id
              AND parent.tenant_id = nullif(current_setting('gaialab.tenant_id', true), '')
        )
    )
    WITH CHECK (
        gaialab_is_operator()
        OR EXISTS (
            SELECT 1
            FROM audit_exports AS parent
            WHERE parent.package_id = audit_export_events.package_id
              AND parent.tenant_id = nullif(current_setting('gaialab.tenant_id', true), '')
        )
    );
