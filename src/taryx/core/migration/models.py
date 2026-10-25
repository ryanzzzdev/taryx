"""Migration evidence schema — cohorts, comparisons, decisions, events.

Comparison evidence is written under the restricted `shadow` database
alias (role taryx_shadow): the database itself denies that credential
INSERT/UPDATE/DELETE on financial and evidence-of-record tables, so
shadow code paths cannot issue invoices or mutate the ledger.
"""

from django.contrib.auth.models import User
from django.db import models

from taryx.core.accounts.models import Account
from taryx.core.pricing.models import RatingRun

SHADOW_ALIAS = "shadow"


class Cohort(models.Model):
    """A named group of accounts migrating through routing modes."""

    class Mode(models.TextChoices):
        LEGACY_ONLY = "legacy_only"
        SHADOW = "shadow"
        NEW_ONLY = "new_only"

    name = models.CharField(max_length=64, unique=True)
    routing_mode = models.CharField(max_length=16, choices=Mode.choices, default=Mode.LEGACY_ONLY)
    routing_revision = models.PositiveIntegerField(default=1)
    members = models.ManyToManyField(Account, through="CohortMembership")
    eval_period_start = models.DateField()
    eval_period_end = models.DateField()
    eval_frozen_at = models.DateTimeField()

    def __str__(self) -> str:
        return f"{self.name} ({self.routing_mode} r{self.routing_revision})"


class CohortMembership(models.Model):
    cohort = models.ForeignKey(Cohort, on_delete=models.CASCADE)
    account = models.ForeignKey(Account, on_delete=models.PROTECT)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("cohort", "account")


class LegacyCalculation(models.Model):
    """A verbatim legacy response persisted as evidence.

    Unique per (snapshot_hash, engine_version, catalogue_version):
    retrying after a legacy restart re-fetches the identical
    deterministic result and resolves to this same row.
    """

    snapshot_hash = models.CharField(max_length=64)
    engine_version = models.CharField(max_length=32)
    catalogue_version = models.CharField(max_length=32)
    request_id = models.CharField(max_length=64)
    response_json = models.JSONField()
    net = models.DecimalField(max_digits=14, decimal_places=2)
    gst = models.DecimalField(max_digits=14, decimal_places=2)
    total = models.DecimalField(max_digits=14, decimal_places=2)
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("snapshot_hash", "engine_version", "catalogue_version")


class ComparisonRun(models.Model):
    """Itemised comparison of one rating run vs the legacy response."""

    class Status(models.TextChoices):
        MATCH = "match"
        DIFFERENCE = "difference"
        INCONCLUSIVE = "inconclusive"

    account = models.ForeignKey(Account, on_delete=models.PROTECT)
    period_start = models.DateField()
    period_end = models.DateField()
    rating_run = models.ForeignKey(RatingRun, null=True, on_delete=models.PROTECT, related_name="+")
    legacy_calculation = models.ForeignKey(
        LegacyCalculation, null=True, on_delete=models.PROTECT, related_name="+"
    )
    snapshot_hash = models.CharField(max_length=64)
    new_engine_version = models.CharField(max_length=32)
    legacy_version_token = models.CharField(max_length=64)
    policy_identity = models.CharField(max_length=64)
    status = models.CharField(max_length=16, choices=Status.choices)
    failure_code = models.CharField(max_length=32, null=True, blank=True)
    report_json = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # Same snapshot + same engines → the same comparison identity;
        # a retry after restart resolves to the existing row.
        unique_together = ("snapshot_hash", "legacy_version_token")


class DiscrepancyDecision(models.Model):
    """A scoped, versioned classification of one specific difference.

    Validity is pinned to the comparison's engine versions, policy
    identity and snapshot hash: any input or engine change invalidates
    the approval for cutover purposes.
    """

    class Classification(models.TextChoices):
        PRESERVE_CLIENT_POLICY = "preserve_client_policy"
        APPROVED_DEFECT_CORRECTION = "approved_defect_correction"

    cohort = models.ForeignKey(Cohort, on_delete=models.PROTECT)
    fingerprint = models.CharField(max_length=64)
    snapshot_hash = models.CharField(max_length=64)
    new_engine_version = models.CharField(max_length=32)
    legacy_version_token = models.CharField(max_length=64)
    policy_identity = models.CharField(max_length=64)
    classification = models.CharField(max_length=40, choices=Classification.choices)
    actor = models.ForeignKey(User, on_delete=models.PROTECT)
    reason = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def is_valid_for(self, comparison: ComparisonRun) -> bool:
        return (
            self.snapshot_hash == comparison.snapshot_hash
            and self.new_engine_version == comparison.new_engine_version
            and self.legacy_version_token == comparison.legacy_version_token
            and self.policy_identity == comparison.policy_identity
        )


class CohortEvent(models.Model):
    """Auditable history of routing and decision transitions."""

    cohort = models.ForeignKey(Cohort, on_delete=models.PROTECT, related_name="events")
    actor = models.ForeignKey(User, null=True, on_delete=models.PROTECT)
    action = models.CharField(max_length=40)
    from_mode = models.CharField(max_length=16, null=True, blank=True)
    to_mode = models.CharField(max_length=16, null=True, blank=True)
    routing_revision = models.PositiveIntegerField()
    detail = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
