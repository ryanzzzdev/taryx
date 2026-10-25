"""Financial-integrity enforcement at the database boundary.

- Sequence for invoice numbering.
- Deferred constraint trigger: every journal entry must have >= 2 postings
  with equal total debits and credits, checked at transaction commit.
- BEFORE UPDATE/DELETE triggers: issued invoices, journal entries and
  postings are immutable at the database level, not just by convention.
"""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("billing", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(
            sql="CREATE SEQUENCE billing_invoice_number_seq START 1",
            reverse_sql="DROP SEQUENCE billing_invoice_number_seq",
        ),
        migrations.RunSQL(
            sql="""
            CREATE OR REPLACE FUNCTION billing_check_journal_balance()
            RETURNS trigger AS $$
            DECLARE
                jid bigint;
            BEGIN
                jid := COALESCE(NEW.journal_id, OLD.journal_id);
                IF (SELECT count(*) FROM billing_posting WHERE journal_id = jid) < 2
                   OR (SELECT coalesce(sum(debit), 0) FROM billing_posting
                       WHERE journal_id = jid)
                      <> (SELECT coalesce(sum(credit), 0) FROM billing_posting
                          WHERE journal_id = jid) THEN
                    RAISE EXCEPTION 'journal % is not balanced', jid
                    USING ERRCODE = '23514';
                END IF;
                RETURN NULL;
            END;
            $$ LANGUAGE plpgsql;

            CREATE CONSTRAINT TRIGGER billing_posting_balance
            AFTER INSERT OR UPDATE OR DELETE ON billing_posting
            DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW EXECUTE FUNCTION billing_check_journal_balance();
            """,
            reverse_sql="""
            DROP TRIGGER IF EXISTS billing_posting_balance ON billing_posting;
            DROP FUNCTION IF EXISTS billing_check_journal_balance;
            """,
        ),
        migrations.RunSQL(
            sql="""
            CREATE OR REPLACE FUNCTION billing_no_mutation()
            RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'issued financial documents are immutable';
            END;
            $$ LANGUAGE plpgsql;

            CREATE TRIGGER billing_invoice_immutable
            BEFORE UPDATE OR DELETE ON billing_invoice
            FOR EACH ROW EXECUTE FUNCTION billing_no_mutation();

            CREATE TRIGGER billing_journalentry_immutable
            BEFORE UPDATE OR DELETE ON billing_journalentry
            FOR EACH ROW EXECUTE FUNCTION billing_no_mutation();

            CREATE TRIGGER billing_posting_immutable
            BEFORE UPDATE OR DELETE ON billing_posting
            FOR EACH ROW EXECUTE FUNCTION billing_no_mutation();
            """,
            reverse_sql="""
            DROP TRIGGER IF EXISTS billing_invoice_immutable ON billing_invoice;
            DROP TRIGGER IF EXISTS billing_journalentry_immutable ON billing_journalentry;
            DROP TRIGGER IF EXISTS billing_posting_immutable ON billing_posting;
            DROP FUNCTION IF EXISTS billing_no_mutation;
            """,
        ),
    ]
