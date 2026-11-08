-- Restricted shadow-evidence role (see migration 0001 grants and
-- settings.DATABASES["shadow"]). Idempotent for fresh volumes.
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'taryx_shadow') THEN
    CREATE ROLE taryx_shadow LOGIN PASSWORD 'taryx_shadow';
  END IF;
END $$;
