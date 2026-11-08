"""Freeze persisted legacy calculations.

A LegacyCalculation is verbatim evidence an issued invoice pins as its
authoritative provenance; mutating it after issuance would rewrite what
a committed financial document explains. UPDATE/DELETE are rejected at
the database level, matching the invoice/journal immutability boundary.
ComparisonRun stays mutable by design — it is observation evidence that
legitimately refreshes on retry; the pinned calculation does not.
"""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("migration", "0003_comparisonrun_updated_at"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
            CREATE OR REPLACE FUNCTION migration_legacycalculation_no_mutation()
            RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'persisted legacy calculations are immutable';
            END;
            $$ LANGUAGE plpgsql;

            CREATE TRIGGER migration_legacycalculation_immutable
            BEFORE UPDATE OR DELETE ON migration_legacycalculation
            FOR EACH ROW EXECUTE FUNCTION migration_legacycalculation_no_mutation();
            """,
            reverse_sql="""
            DROP TRIGGER IF EXISTS migration_legacycalculation_immutable
                ON migration_legacycalculation;
            DROP FUNCTION IF EXISTS migration_legacycalculation_no_mutation;
            """,
        ),
    ]
