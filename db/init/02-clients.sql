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
  -- Per-client shadow credential (M4-F9): the shared taryx_shadow role
  -- must never reach another client's database.
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'taryx_shadow_sg') THEN
    CREATE ROLE taryx_shadow_sg LOGIN PASSWORD 'taryx_shadow_sg';
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
-- and by its own shadow-evidence role. The shared taryx_shadow role
-- is an aurora credential and is denied CONNECT here.
REVOKE CONNECT ON DATABASE taryx_southgrid FROM PUBLIC;
REVOKE CONNECT ON DATABASE taryx_southgrid FROM taryx_shadow;
GRANT CONNECT ON DATABASE taryx_southgrid TO taryx_sg;
GRANT CONNECT ON DATABASE taryx_southgrid TO taryx_shadow_sg;

-- Per-database resolution used by migration 0005: the southgrid
-- database's shadow role is taryx_shadow_sg, not the aurora one.
ALTER DATABASE taryx_southgrid SET taryx.shadow_role TO 'taryx_shadow_sg';

-- Aurora's application role must NOT be a member of the bootstrap
-- superuser: SET ROLE would restore full power and bypass every ACL
-- above. Instead it owns the application objects outright — migrations
-- (ALTER TABLE) and runtime writes need ownership, which grants alone
-- cannot give. The superuser keeps only database-level provisioning.
-- CREATEROLE covers the migration-time CREATE ROLE for taryx_shadow.
REVOKE taryx FROM taryx_app;
GRANT USAGE, CREATE ON SCHEMA public TO taryx_app;
DO $$
DECLARE
    obj record;
BEGIN
    -- Column-linked sequences carry their table's owner automatically.
    FOR obj IN
        SELECT c.relname, c.relkind
        FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relkind IN ('r', 'v', 'm')
    LOOP
        EXECUTE format(
            'ALTER %s %I OWNER TO taryx_app',
            CASE obj.relkind
                WHEN 'r' THEN 'TABLE'
                WHEN 'v' THEN 'VIEW'
                WHEN 'm' THEN 'MATERIALIZED VIEW'
            END,
            obj.relname
        );
    END LOOP;
END $$;

-- The southgrid app role needs CREATEROLE for the same migration-time
-- shadow-role creation when it migrates first on a fresh cluster.
ALTER ROLE taryx_sg CREATEROLE;
