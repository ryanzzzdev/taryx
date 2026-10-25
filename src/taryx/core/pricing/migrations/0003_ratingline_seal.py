"""Seal published rating runs: lines may only be added by the run's
creating transaction.

The UPDATE/DELETE triggers stop tampering with existing lines, but an
INSERT of a new RatingLine into an issued run succeeded — silently
changing the itemisation behind immutable totals and the amounts billing
derives from run.lines. Same mechanism as the journal seal: the run's
insert marks it open via a transaction-local setting that dies with the
(sub)transaction, and the line trigger only admits legs for open runs.
"""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("pricing", "0002_snapshot_and_immutability"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
            CREATE OR REPLACE FUNCTION pricing_run_open()
            RETURNS trigger AS $$
            BEGIN
                PERFORM set_config('pricing.open_run_' || NEW.id, 'on', true);
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;

            CREATE TRIGGER pricing_ratingrun_open
            AFTER INSERT ON pricing_ratingrun
            FOR EACH ROW EXECUTE FUNCTION pricing_run_open();

            CREATE OR REPLACE FUNCTION pricing_line_sealed_run()
            RETURNS trigger AS $$
            BEGIN
                IF coalesce(
                    current_setting('pricing.open_run_' || NEW.run_id, true),
                    'off'
                ) <> 'on' THEN
                    RAISE EXCEPTION
                        'rating run % is sealed: lines may only be added '
                        'in the transaction that created it', NEW.run_id
                    USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;

            CREATE TRIGGER pricing_ratingline_sealed
            BEFORE INSERT ON pricing_ratingline
            FOR EACH ROW EXECUTE FUNCTION pricing_line_sealed_run();
            """,
            reverse_sql="""
            DROP TRIGGER IF EXISTS pricing_ratingline_sealed ON pricing_ratingline;
            DROP FUNCTION IF EXISTS pricing_line_sealed_run;
            DROP TRIGGER IF EXISTS pricing_ratingrun_open ON pricing_ratingrun;
            DROP FUNCTION IF EXISTS pricing_run_open;
            """,
        ),
    ]
