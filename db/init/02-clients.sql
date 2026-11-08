-- Second-client isolation: southgrid gets its own database and role,
-- and the aurora database is closed to every other login. Safe to run
-- repeatedly (fresh-volume initdb and the db-init service share it).
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'taryx_sg') THEN
    CREATE ROLE taryx_sg LOGIN PASSWORD 'taryx_sg';
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'taryx_app') THEN
    CREATE ROLE taryx_app LOGIN PASSWORD 'taryx_app' CREATEROLE;
  END IF;
END $$;

SELECT 'CREATE DATABASE taryx_southgrid OWNER taryx_sg'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'taryx_southgrid')
\gexec

REVOKE CONNECT ON DATABASE taryx FROM PUBLIC;
GRANT CONNECT ON DATABASE taryx TO taryx;
GRANT CONNECT ON DATABASE taryx TO taryx_app;
GRANT CONNECT ON DATABASE taryx TO taryx_shadow;

-- Symmetric closure: taryx_southgrid is reachable only by its owner
-- and by the shared shadow-evidence role (its privileges inside the
-- database are granted per-database by the migration grants).
REVOKE CONNECT ON DATABASE taryx_southgrid FROM PUBLIC;
GRANT CONNECT ON DATABASE taryx_southgrid TO taryx_sg;
GRANT CONNECT ON DATABASE taryx_southgrid TO taryx_shadow;

-- Aurora's application role is a member of the bootstrap owner, so it
-- holds owner privileges on every taryx-owned object — but membership
-- never inherits SUPERUSER, so it stays subject to the ACLs above.
-- CREATEROLE covers the migration-time CREATE ROLE for taryx_shadow.
GRANT taryx TO taryx_app;
