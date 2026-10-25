"""Source interval records are immutable history.

Ingestion only ever inserts records; revisions arrive as new rows. A
database trigger makes that append-only contract enforceable — nothing
may rewrite the readings pinned by a rating run's input digest.
"""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("metering", "0002_intervalrecord_method_code"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
            CREATE OR REPLACE FUNCTION metering_record_immutable()
            RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'ingested interval records are immutable';
            END;
            $$ LANGUAGE plpgsql;

            CREATE TRIGGER metering_intervalrecord_immutable
            BEFORE UPDATE OR DELETE ON metering_intervalrecord
            FOR EACH ROW EXECUTE FUNCTION metering_record_immutable();
            """,
            reverse_sql="""
            DROP TRIGGER IF EXISTS metering_intervalrecord_immutable
                ON metering_intervalrecord;
            DROP FUNCTION IF EXISTS metering_record_immutable;
            """,
        ),
    ]
