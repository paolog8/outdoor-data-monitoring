-- SymmetricDS creates database triggers on user tables to capture changes.
-- sym_user needs TRIGGER privilege on all tables for this to work.

GRANT TRIGGER ON ALL TABLES IN SCHEMA public TO sym_user;

ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT TRIGGER ON TABLES TO sym_user;
