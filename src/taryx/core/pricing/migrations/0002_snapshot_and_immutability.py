"""Persist the pinned input snapshot and immutabilise rating evidence.

input_snapshot retains the exact digest payload (interval selections,
agreements, tariff specs, open quarantines, versions) so a published
calculation can be reconstructed without trusting mutable referenced
metadata. Rating runs and lines are calculation evidence: UPDATE/DELETE
are forbidden at the database boundary, matching the financial triggers.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("pricing", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="ratingrun",
            name="input_snapshot",
            field=models.JSONField(default=dict),
        ),
        migrations.RunSQL(
            sql="""
            CREATE OR REPLACE FUNCTION pricing_no_mutation()
            RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'published rating evidence is immutable';
            END;
            $$ LANGUAGE plpgsql;

            CREATE TRIGGER pricing_ratingrun_immutable
            BEFORE UPDATE OR DELETE ON pricing_ratingrun
            FOR EACH ROW EXECUTE FUNCTION pricing_no_mutation();

            CREATE TRIGGER pricing_ratingline_immutable
            BEFORE UPDATE OR DELETE ON pricing_ratingline
            FOR EACH ROW EXECUTE FUNCTION pricing_no_mutation();
            """,
            reverse_sql="""
            DROP TRIGGER IF EXISTS pricing_ratingrun_immutable ON pricing_ratingrun;
            DROP TRIGGER IF EXISTS pricing_ratingline_immutable ON pricing_ratingline;
            DROP FUNCTION IF EXISTS pricing_no_mutation;
            """,
        ),
    ]
