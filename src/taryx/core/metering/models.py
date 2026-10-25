from django.db import models
from django.db.models import Q

from taryx.core.accounts.models import MeterChannel


class IngestionBatch(models.Model):
    class Status(models.TextChoices):
        PUBLISHED = "published"
        REJECTED = "rejected"
        DUPLICATE = "duplicate"

    source_name = models.CharField(max_length=200)
    content_sha256 = models.CharField(max_length=64)
    received_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=16, choices=Status.choices)
    record_count = models.PositiveIntegerField(default=0)
    accepted_count = models.PositiveIntegerField(default=0)
    quarantined_count = models.PositiveIntegerField(default=0)
    error_code = models.CharField(max_length=40, null=True, blank=True)
    error_detail = models.TextField(blank=True)
    duplicate_of = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="duplicates"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["content_sha256"],
                condition=~Q(status="duplicate"),
                name="uniq_active_batch_hash",
            )
        ]


class IntervalRecord(models.Model):
    batch = models.ForeignKey(
        IngestionBatch, on_delete=models.CASCADE, related_name="interval_records"
    )
    channel = models.ForeignKey(
        MeterChannel, on_delete=models.CASCADE, related_name="interval_records"
    )
    interval_date = models.DateField()
    interval_number = models.PositiveIntegerField()
    interval_end_utc = models.DateTimeField()
    value = models.DecimalField(max_digits=18, decimal_places=6)
    quality = models.CharField(max_length=1)
    reason_code = models.CharField(max_length=8, null=True, blank=True)
    update_dt = models.DateTimeField(null=True)
    msats_load_dt = models.DateTimeField(null=True)
    row_number = models.PositiveIntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["batch", "channel", "interval_date", "interval_number"],
                name="uniq_record_position",
            )
        ]
        indexes = [
            models.Index(fields=["channel", "interval_end_utc"]),
        ]


class CurrentInterval(models.Model):
    channel = models.ForeignKey(
        MeterChannel, on_delete=models.CASCADE, related_name="current_intervals"
    )
    interval_end_utc = models.DateTimeField()
    value = models.DecimalField(max_digits=18, decimal_places=6)
    quality = models.CharField(max_length=1)
    source_record = models.ForeignKey(IntervalRecord, on_delete=models.PROTECT)
    selection_version = models.PositiveIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["channel", "interval_end_utc"], name="uniq_current_interval"
            )
        ]


class QuarantinedInterval(models.Model):
    class Status(models.TextChoices):
        OPEN = "open"
        RESOLVED = "resolved"

    channel = models.ForeignKey(
        MeterChannel, on_delete=models.CASCADE, related_name="quarantined_intervals"
    )
    interval_end_utc = models.DateTimeField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.OPEN)
    candidate_records = models.ManyToManyField(IntervalRecord, related_name="+")
    detail = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["channel", "interval_end_utc", "status"],
                condition=Q(status="open"),
                name="uniq_open_quarantine",
            )
        ]
