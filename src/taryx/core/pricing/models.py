from django.db import models

from taryx.core.accounts.models import Account, TariffAgreement


class RatingRun(models.Model):
    """Immutable persisted result of one deterministic rating calculation.

    input_digest pins the exact interval selections, agreements, tariff
    identity, GST rate and engine/policy versions consumed; input_snapshot
    retains that payload verbatim so a historical calculation can be
    reconstructed without trusting mutable referenced metadata. Both the
    run and its lines are immutable at the database boundary (migration).
    """

    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="rating_runs")
    period_start = models.DateField()
    period_end = models.DateField()
    engine_version = models.CharField(max_length=16)
    policy_identity = models.CharField(max_length=80)
    input_digest = models.CharField(max_length=64)
    input_snapshot = models.JSONField(default=dict)
    net = models.DecimalField(max_digits=14, decimal_places=2)
    gst = models.DecimalField(max_digits=14, decimal_places=2)
    total = models.DecimalField(max_digits=14, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)


class RatingLine(models.Model):
    class Element(models.TextChoices):
        IMPORT = "import"
        EXPORT_CREDIT = "export_credit"
        SUPPLY = "supply"

    run = models.ForeignKey(RatingRun, on_delete=models.CASCADE, related_name="lines")
    sequence = models.PositiveIntegerField()
    agreement = models.ForeignKey(TariffAgreement, on_delete=models.PROTECT)
    tariff_code = models.CharField(max_length=32)
    segment_from = models.DateField()
    segment_to = models.DateField("segment last day (inclusive)")
    element = models.CharField(max_length=16, choices=Element.choices)
    band = models.CharField(max_length=16, null=True, blank=True)
    quantity = models.DecimalField(max_digits=18, decimal_places=6)
    unit = models.CharField(max_length=8)
    rate = models.DecimalField(max_digits=12, decimal_places=6)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    gst = models.DecimalField(max_digits=14, decimal_places=2)
    basis = models.CharField(max_length=300)
