"""Seal posted journals: postings may only be added by the journal's
creating transaction.

The balance trigger guarantees a journal balances at commit, but nothing
stopped a later transaction from appending a balanced pair — silently
changing the recognised liability behind an immutable invoice. A journal
insert marks itself open via a transaction-local setting (set_config
is_local), which dies with the (sub)transaction; the posting trigger only
admits legs for open journals, so once the creating transaction commits
no later leg can ever attach.
"""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("billing", "0003_corrections"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
            CREATE OR REPLACE FUNCTION billing_journal_open()
            RETURNS trigger AS $$
            BEGIN
                PERFORM set_config('billing.open_journal_' || NEW.id, 'on', true);
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;

            CREATE TRIGGER billing_journalentry_open
            AFTER INSERT ON billing_journalentry
            FOR EACH ROW EXECUTE FUNCTION billing_journal_open();

            CREATE OR REPLACE FUNCTION billing_posting_sealed_journal()
            RETURNS trigger AS $$
            BEGIN
                IF coalesce(
                    current_setting('billing.open_journal_' || NEW.journal_id, true),
                    'off'
                ) <> 'on' THEN
                    RAISE EXCEPTION
                        'journal % is sealed: postings may only be added '
                        'in the transaction that created it', NEW.journal_id
                    USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;

            CREATE TRIGGER billing_posting_sealed
            BEFORE INSERT ON billing_posting
            FOR EACH ROW EXECUTE FUNCTION billing_posting_sealed_journal();
            """,
            reverse_sql="""
            DROP TRIGGER IF EXISTS billing_posting_sealed ON billing_posting;
            DROP FUNCTION IF EXISTS billing_posting_sealed_journal;
            DROP TRIGGER IF EXISTS billing_journalentry_open ON billing_journalentry;
            DROP FUNCTION IF EXISTS billing_journal_open;
            """,
        ),
    ]
