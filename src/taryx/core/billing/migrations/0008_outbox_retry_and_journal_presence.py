"""Close the empty-journal gap and record outbox retry state.

The posting trigger only schedules the deferred balance check when a
posting changes, so a journal header committed without any legs bypassed
the >=2 balanced-posting invariant and then sealed permanently. A second
deferred constraint trigger on journal insert applies the same check at
commit: valid journals (legs added later in the same transaction) pass;
a journal reaching commit with no postings is rejected.

OutboxEvent.attempts/last_error retain observable retry state so the
drain can isolate per-event failures and bound starvation (services).
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("billing", "0007_remove_adjustment_uniq_adjustment_digest"),
    ]

    operations = [
        migrations.AddField(
            model_name="outboxevent",
            name="attempts",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="outboxevent",
            name="last_error",
            field=models.TextField(blank=True),
        ),
        migrations.RunSQL(
            sql="""
            CREATE OR REPLACE FUNCTION billing_check_journal_present()
            RETURNS trigger AS $$
            BEGIN
                IF (SELECT count(*) FROM billing_posting WHERE journal_id = NEW.id) < 2
                   OR (SELECT coalesce(sum(debit), 0) FROM billing_posting
                       WHERE journal_id = NEW.id)
                      <> (SELECT coalesce(sum(credit), 0) FROM billing_posting
                          WHERE journal_id = NEW.id) THEN
                    RAISE EXCEPTION 'journal % is not balanced', NEW.id
                    USING ERRCODE = '23514';
                END IF;
                RETURN NULL;
            END;
            $$ LANGUAGE plpgsql;

            CREATE CONSTRAINT TRIGGER billing_journalentry_present
            AFTER INSERT ON billing_journalentry
            DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW EXECUTE FUNCTION billing_check_journal_present();
            """,
            reverse_sql="""
            DROP TRIGGER IF EXISTS billing_journalentry_present ON billing_journalentry;
            DROP FUNCTION IF EXISTS billing_check_journal_present;
            """,
        ),
    ]
