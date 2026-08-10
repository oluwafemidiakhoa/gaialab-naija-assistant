-- GaiaLab Naija Trust Rail / least-privilege observability
-- Migration: 0004_observability

CREATE OR REPLACE FUNCTION gaialab_current_role_kind()
RETURNS TEXT
LANGUAGE SQL
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
    SELECT role_kind
    FROM public.gaialab_database_roles
    WHERE role_name = SESSION_USER
    LIMIT 1;
$$;

REVOKE ALL ON FUNCTION gaialab_current_role_kind() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION gaialab_current_role_kind() TO PUBLIC;
