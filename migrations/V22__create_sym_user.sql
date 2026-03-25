-- Creates a dedicated SymmetricDS database user with the minimum permissions
-- needed to operate on the outdoor_monitoring database.
--
-- The password is set via the SYM_PASSWORD environment variable, substituted
-- by Flyway at migration time. Add SYM_PASSWORD to your .env file.
--
-- Permissions granted:
--   - USAGE on the public schema
--   - CREATE on the public schema (SymmetricDS needs to create its sym_* tables)
--   - SELECT, INSERT, UPDATE, DELETE on all existing user tables
--   - Same rights automatically applied to future tables via ALTER DEFAULT PRIVILEGES

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'sym_user') THEN
        CREATE ROLE sym_user WITH LOGIN PASSWORD '${SYM_PASSWORD}';
    END IF;
END
$$;

GRANT USAGE ON SCHEMA public TO sym_user;
GRANT CREATE ON SCHEMA public TO sym_user;

GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO sym_user;

ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO sym_user;
