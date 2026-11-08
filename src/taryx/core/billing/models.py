from django.db import models
from django.db.models import Q

from taryx.core.accounts.models import Account
from taryx.core.pricing.models import RatingRun


class BillingOperation(models.Model):
    """Durable admission of a billing intent.

    operation_id is the operator's idempotency key: re-admission with the
    same payload returns this row; the same id with a different payload is
    a conflict rejected at admission.
    """

    class Status(models.TextChoices):
        PENDING = "pending"
        COMPLETE = "complete"
        STALE = "stale"

    operation_id = models.CharField(max_length=64, unique=True)
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="billing_ops")
    period_start = models.DateField()
    period_end = models.DateField()
    rating_run = models.ForeignKey(RatingRun, on_delete=models.PROTECT, related_name="billing_ops")
    payload_sha256 = models.CharField(max_length=64)
    # Cohort routing pinned at admission (resolved by the caller — billing
    # stays unaware of the migration app): which engine is authoritative
    # for this op and which routing revision it was admitted under.
    cohort_mode = models.CharField(max_length=16, default="new_only")
    cohort_revision = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    invoice = models.ForeignKey(
        "Invoice", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    adjustment = models.ForeignKey(
        "Adjustment", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    detail = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True)


class OutboxEvent(models.Model):
    """Durable publication intent; survives broker downtime.

    A consumer marks delivered_at only inside the same transaction that
    produces the business outcome, so at-least-once processing is safe and
    a lost task is recovered by the outbox drain.
    """

    operation = models.OneToOneField(
        BillingOperation, on_delete=models.CASCADE, related_name="outbox_event"
    )
    topic = models.CharField(max_length=64, default="billing.issue")
    created_at = models.DateTimeField(auto_now_add=True)
    delivered_at = models.DateTimeField(null=True)
    # Observable retry state: each failed drain attempt is recorded so one
    # failing event neither disappears nor starves later events forever.
    attempts = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True)


class Invoice(models.Model):
    """Immutable issued invoice. UPDATE/DELETE are forbidden by a database
    trigger (see migration); the (account, period, input_digest) generation
    key makes double issuance structurally impossible."""

    number = models.CharField(max_length=20, unique=True)
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="invoices")
    period_start = models.DateField()
    period_end = models.DateField()
    rating_run = models.ForeignKey(RatingRun, on_delete=models.PROTECT)
    input_digest = models.CharField(max_length=64)
    # "new" = Taryx rating run; "legacy" = authoritative figures from the
    # pinned legacy calculation (cohort routing modes legacy/shadow).
    calculation_source = models.CharField(max_length=8, default="new")
    # Authoritative legacy evidence pinned at issuance: the shadow-alias
    # LegacyCalculation row id whose response produced these figures (a
    # plain int — cross-database foreign keys cannot be enforced).
    legacy_calculation_id = models.PositiveIntegerField(null=True)
    net = models.DecimalField(max_digits=14, decimal_places=2)
    gst = models.DecimalField(max_digits=14, decimal_places=2)
    total = models.DecimalField(max_digits=14, decimal_places=2)
    issued_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["account", "period_start", "period_end", "input_digest"],
                name="uniq_bill_generation",
            )
        ]


class Adjustment(models.Model):
    """Immutable correction appended to an issued invoice.

    Deltas reconcile revised liability against the net liability already
    recognised by the invoice and all prior adjustments — never against
    the original total alone. A zero-delta adjustment is audit evidence
    only and carries no journal."""

    number = models.CharField(max_length=20, unique=True)
    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name="adjustments")
    rating_run = models.ForeignKey(RatingRun, on_delete=models.PROTECT)
    input_digest = models.CharField(max_length=64)
    # Authoritative engine for this generation — the same input digest
    # under a different engine is a different generation, not a retry.
    calculation_source = models.CharField(max_length=8, default="new")
    generation = models.PositiveIntegerField()
    delta_charge = models.DecimalField(max_digits=14, decimal_places=2)
    delta_export = models.DecimalField(max_digits=14, decimal_places=2)
    delta_gst = models.DecimalField(max_digits=14, decimal_places=2)
    delta_total = models.DecimalField(max_digits=14, decimal_places=2)
    issued_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            # (invoice, generation) is the financial generation identity.
            # Digest is intentionally NOT unique: legitimate successive
            # routing transitions may correct the same inputs under a
            # different authoritative engine (legacy→new→legacy→…), while
            # retry idempotency is enforced by the recognised-generation
            # check under the operation lock.
            models.UniqueConstraint(
                fields=["invoice", "generation"], name="uniq_adjustment_generation"
            ),
        ]


class JournalEntry(models.Model):
    """Immutable journal header; balance across its postings is enforced by
    a deferred database constraint trigger at commit."""

    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name="journal_entries")
    adjustment = models.ForeignKey(
        Adjustment, null=True, blank=True, on_delete=models.PROTECT, related_name="journal_entries"
    )
    operation = models.ForeignKey(
        BillingOperation, on_delete=models.PROTECT, related_name="journal_entries"
    )
    posted_at = models.DateTimeField(auto_now_add=True)
    memo = models.CharField(max_length=200)


class Posting(models.Model):
    """One debit or credit leg of a journal entry (never both)."""

    journal = models.ForeignKey(JournalEntry, on_delete=models.PROTECT, related_name="postings")
    account_code = models.CharField(max_length=4)
    debit = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    credit = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    memo = models.CharField(max_length=200, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(debit__gte=0) & Q(credit__gte=0) & ~(Q(debit__gt=0) & Q(credit__gt=0)),
                name="posting_single_leg",
            )
        ]
