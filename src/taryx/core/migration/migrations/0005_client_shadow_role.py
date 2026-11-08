"""Per-client shadow credential (M4 review finding F9).

The shared `taryx_shadow` role could connect to and read every client's
account tables — a shared runtime credential is not an isolation
boundary. Each deployment resolves its own shadow role through the
per-database setting `taryx.shadow_role` (aurora keeps `taryx_shadow`,
southgrid resolves `taryx_shadow_sg`). Where the resolved role differs
from `taryx_shadow`, this migration strips the shared role's object
privileges inside that database and re-issues the 0001 grant set to
the client-scoped role.
"""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("migration", "0004_legacycalculation_immutable"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
            DO $$
            DECLARE
                shadow_role text := coalesce(
                    nullif(current_setting('taryx.shadow_role', true), ''),
                    'taryx_shadow'
                );
            BEGIN
                IF shadow_role = 'taryx_shadow' THEN
                    RETURN;
                END IF;
                -- The shared credential holds no object privileges in
                -- a client database that resolves its own shadow role.
                REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public
                    FROM taryx_shadow;
                REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public
                    FROM taryx_shadow;
                REVOKE USAGE ON SCHEMA public FROM taryx_shadow;
                IF EXISTS (SELECT FROM pg_roles WHERE rolname = shadow_role) THEN
                    EXECUTE format('GRANT USAGE ON SCHEMA public TO %I', shadow_role);
                    EXECUTE format(
                        'GRANT SELECT ON ALL TABLES IN SCHEMA public TO %I',
                        shadow_role
                    );
                    EXECUTE format(
                        'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO %I',
                        shadow_role
                    );
                    EXECUTE format(
                        'GRANT INSERT, UPDATE, DELETE ON TABLE '
                        'migration_legacycalculation, migration_comparisonrun TO %I',
                        shadow_role
                    );
                    EXECUTE format(
                        'REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON TABLE '
                        'billing_invoice, billing_journalentry, billing_posting, '
                        'billing_adjustment, billing_billingoperation, '
                        'billing_outboxevent, pricing_ratingrun, '
                        'pricing_ratingline, metering_intervalrecord, '
                        'metering_currentinterval, metering_quarantinedinterval, '
                        'metering_ingestionbatch FROM %I',
                        shadow_role
                    );
                END IF;
            END $$;
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
