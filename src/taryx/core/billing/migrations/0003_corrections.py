"""Successive corrections: immutable linked adjustments (TAR-008).

- Adjustment documents hang off the root invoice with a per-invoice
  generation and digest uniqueness (repeated correction is structurally
  a no-op).
- Journals trace to the posting operation and, for corrections, the
  adjustment document.
- Adjustments join the immutability trigger set; the posting balance
  trigger already covers correction journals.
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("billing", "0002_financial_integrity"),
    ]

    operations = [
        migrations.CreateModel(
            name="Adjustment",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("number", models.CharField(max_length=20, unique=True)),
                ("input_digest", models.CharField(max_length=64)),
                ("generation", models.PositiveIntegerField()),
                ("delta_charge", models.DecimalField(decimal_places=2, max_digits=14)),
                ("delta_export", models.DecimalField(decimal_places=2, max_digits=14)),
                ("delta_gst", models.DecimalField(decimal_places=2, max_digits=14)),
                ("delta_total", models.DecimalField(decimal_places=2, max_digits=14)),
                ("issued_at", models.DateTimeField(auto_now_add=True)),
                (
                    "invoice",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="adjustments",
                        to="billing.invoice",
                    ),
                ),
                (
                    "rating_run",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT, to="pricing.ratingrun"
                    ),
                ),
            ],
        ),
        migrations.AddField(
            model_name="billingoperation",
            name="adjustment",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="+",
                to="billing.adjustment",
            ),
        ),
        migrations.AddField(
            model_name="journalentry",
            name="adjustment",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="journal_entries",
                to="billing.adjustment",
            ),
        ),
        migrations.AddField(
            model_name="journalentry",
            name="operation",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="journal_entries",
                to="billing.billingoperation",
            ),
        ),
        # One-time administrative backfill: the immutability trigger is
        # suspended for this statement only, then restored immediately.
        migrations.RunSQL(
            sql="""
            ALTER TABLE billing_journalentry
                DISABLE TRIGGER billing_journalentry_immutable;
            UPDATE billing_journalentry je
            SET operation_id = (
                SELECT bo.id FROM billing_billingoperation bo
                WHERE bo.invoice_id = je.invoice_id
                ORDER BY bo.id LIMIT 1
            );
            ALTER TABLE billing_journalentry
                ENABLE TRIGGER billing_journalentry_immutable;
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.AlterField(
            model_name="journalentry",
            name="operation",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="journal_entries",
                to="billing.billingoperation",
            ),
        ),
        migrations.AddConstraint(
            model_name="adjustment",
            constraint=models.UniqueConstraint(
                fields=("invoice", "generation"), name="uniq_adjustment_generation"
            ),
        ),
        migrations.AddConstraint(
            model_name="adjustment",
            constraint=models.UniqueConstraint(
                fields=("invoice", "input_digest"), name="uniq_adjustment_digest"
            ),
        ),
        migrations.RunSQL(
            sql="CREATE SEQUENCE billing_adjustment_number_seq START 1",
            reverse_sql="DROP SEQUENCE billing_adjustment_number_seq",
        ),
        migrations.RunSQL(
            sql="""
            CREATE TRIGGER billing_adjustment_immutable
            BEFORE UPDATE OR DELETE ON billing_adjustment
            FOR EACH ROW EXECUTE FUNCTION billing_no_mutation();
            """,
            reverse_sql=(
                "DROP TRIGGER IF EXISTS billing_adjustment_immutable ON billing_adjustment;"
            ),
        ),
    ]
