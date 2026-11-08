import uuid

from django.db import models

from taryx.core.accounts.models import SupplyPoint


class TransferWorkflow(models.Model):
    """Durable market workflow for one synthetic transfer request.

    correlation_id is immutable for the life of the workflow — retries
    resubmit the same id/digest; a new business attempt is a new row.
    Transition rules are frozen in decision 005.
    """

    class State(models.TextChoices):
        DRAFT = "draft"
        SUBMITTED = "submitted"
        RECONCILING = "reconciling"
        COMPLETED = "completed"
        REJECTED = "rejected"
        FAILED = "failed"

    correlation_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    supply_point = models.ForeignKey(
        SupplyPoint, on_delete=models.PROTECT, related_name="transfer_workflows"
    )
    effective_date = models.DateField()
    request_digest = models.CharField(max_length=64)
    state = models.CharField(max_length=16, choices=State.choices, default=State.DRAFT)
    last_applied_seq = models.IntegerField(default=-1)
    attempts = models.PositiveIntegerField(default=0)
    deadline_at = models.DateTimeField(null=True)
    reconcile_deadline_at = models.DateTimeField(null=True)
    last_counterparty_status = models.CharField(max_length=16, blank=True)
    detail = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["state", "deadline_at"])]

    def __str__(self):
        return f"{self.correlation_id}:{self.state}"


TERMINAL_STATES = {
    TransferWorkflow.State.COMPLETED,
    TransferWorkflow.State.REJECTED,
    TransferWorkflow.State.FAILED,
}


class MarketInbox(models.Model):
    """Received callback record; (correlation_id, seq) is the dedup key.

    `note` records how the row was classified — applied, duplicate,
    late — so the full arrival history is inspectable even when the
    workflow state does not move.
    """

    workflow = models.ForeignKey(
        TransferWorkflow,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="inbox",
    )
    correlation_id = models.UUIDField()
    seq = models.IntegerField()
    outcome = models.CharField(max_length=16)
    payload = models.JSONField()
    note = models.CharField(max_length=16, default="applied")
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["correlation_id", "seq"], name="market_inbox_dedup")
        ]


class MarketException(models.Model):
    """Inspectable parking lot for inbound events that match no workflow."""

    correlation_id = models.UUIDField(null=True, blank=True)
    reason = models.CharField(max_length=32)
    raw = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)


class MarketOutbox(models.Model):
    """Durable intent to apply a terminal outcome to core state.

    Delivered transactionally by the drain: the supply-point update and
    delivered_at commit together, so at-least-once delivery is safe.
    """

    workflow = models.OneToOneField(
        TransferWorkflow, on_delete=models.CASCADE, related_name="outbox_event"
    )
    topic = models.CharField(max_length=64, default="market.transfer_completed")
    payload = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)
    delivered_at = models.DateTimeField(null=True)
    attempts = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True)
