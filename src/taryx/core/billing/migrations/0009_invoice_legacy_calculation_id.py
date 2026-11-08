"""Pin authoritative legacy evidence on issued invoices.

A legacy-routed invoice's figures come from a persisted LegacyCalculation
response (shadow alias); recording its row id lets the explanation path
render the authoritative line items rather than the new-engine
comparison run. Stored as a plain integer — cross-database foreign keys
cannot be enforced.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("billing", "0008_outbox_retry_and_journal_presence"),
    ]

    operations = [
        migrations.AddField(
            model_name="invoice",
            name="legacy_calculation_id",
            field=models.PositiveIntegerField(null=True),
        ),
    ]
