"""Batch ingestion: stage, validate and publish NEM12 data atomically.

A batch either publishes fully (records stored, current selection updated)
or is rejected with a stable error code — never a partially visible dataset.

Publication of the current selection is optimistic: candidates are first
evaluated without locks, then every affected interval is re-evaluated and
written under a per-interval row lock in deterministic order. A writer that
raced a concurrent commit therefore re-reads the winner's records instead of
publishing stale results, and equal-precedence conflicts still quarantine.
"""

import hashlib
from dataclasses import dataclass
from datetime import date, datetime

from django.db import transaction
from django.db.utils import IntegrityError
from django.utils import timezone

from taryx.core.accounts.models import MeterChannel
from taryx.core.metering.models import (
    CurrentInterval,
    IngestionBatch,
    IntervalRecord,
    QuarantinedInterval,
)
from taryx.core.metering.nem12 import ChannelData, ChannelMeta, Nem12Error, parse_nem12
from taryx.core.metering.nem_time import nem_interval_end_utc
from taryx.core.metering.selection import precedence, select_current


@dataclass(frozen=True)
class IngestResult:
    batch: IngestionBatch


def _duplicate_of_original(content_hash: str, source_name: str) -> IngestionBatch:
    original = (
        IngestionBatch.objects.exclude(status=IngestionBatch.Status.DUPLICATE)
        .filter(content_sha256=content_hash)
        .get()
    )
    return IngestionBatch.objects.create(
        source_name=source_name,
        content_sha256=content_hash,
        status=IngestionBatch.Status.DUPLICATE,
        duplicate_of=original,
    )


def ingest_nem12_content(content: bytes, source_name: str) -> IngestResult:
    content_hash = hashlib.sha256(content).hexdigest()
    if (
        IngestionBatch.objects.exclude(status=IngestionBatch.Status.DUPLICATE)
        .filter(content_sha256=content_hash)
        .exists()
    ):
        return IngestResult(_duplicate_of_original(content_hash, source_name))

    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        return IngestResult(
            _record_outcome(
                content_hash,
                source_name,
                IngestionBatch.Status.REJECTED,
                error_code="invalid_encoding",
                error_detail=f"bytes are not valid UTF-8: {exc}",
            )
        )

    try:
        meta, channels = parse_nem12(text)
        batch = _publish(content_hash, source_name, meta, channels)
    except Nem12Error as exc:
        batch = _record_outcome(
            content_hash,
            source_name,
            IngestionBatch.Status.REJECTED,
            error_code=exc.code,
            error_detail=str(exc),
        )
    return IngestResult(batch)


def _record_outcome(
    content_hash: str, source_name: str, status: str, **fields: object
) -> IngestionBatch:
    """Insert a batch outcome row; lose the hash race gracefully as a duplicate.

    The savepoint confines the unique-violation so the caller's transaction
    state is untouched, and the loser resolves the actual winner — published
    or rejected — rather than assuming one status.
    """
    try:
        with transaction.atomic():
            return IngestionBatch.objects.create(
                source_name=source_name,
                content_sha256=content_hash,
                status=status,
                **fields,
            )
    except IntegrityError:
        return _duplicate_of_original(content_hash, source_name)


def _publish(
    content_hash: str,
    source_name: str,
    meta: dict[tuple[str, str], ChannelMeta],
    channels: list[ChannelData],
) -> IngestionBatch:
    channel_rows = _resolve_channels(meta)
    with transaction.atomic():
        batch = _record_outcome(content_hash, source_name, IngestionBatch.Status.PUBLISHED)
        if batch.status == IngestionBatch.Status.DUPLICATE:
            return batch

        records: list[IntervalRecord] = []
        for data in channels:
            channel = channel_rows[(data.nmi, data.suffix)]
            for day in data.days:
                for item in day.values:
                    records.append(
                        IntervalRecord(
                            batch=batch,
                            channel=channel,
                            interval_date=day.interval_date,
                            interval_number=item.interval_number,
                            interval_end_utc=nem_interval_end_utc(
                                day.interval_date,
                                item.interval_number,
                                channel.interval_minutes,
                            ),
                            value=item.value,
                            quality=item.quality or "",
                            method_code=item.method_code,
                            reason_code=item.reason_code,
                            update_dt=item.update_dt,
                            msats_load_dt=item.msats_load_dt,
                            row_number=day.row_number,
                        )
                    )
        IntervalRecord.objects.bulk_create(records)

        affected = sorted({(r.channel_id, r.interval_end_utc) for r in records})
        accepted = _apply_selection(batch, affected)
        batch.record_count = len(records)
        batch.accepted_count = accepted
        batch.quarantined_count = (
            QuarantinedInterval.objects.filter(candidate_records__batch=batch).distinct().count()
        )
        batch.save(update_fields=["record_count", "accepted_count", "quarantined_count"])
    return batch


def _resolve_channels(
    meta: dict[tuple[str, str], ChannelMeta],
) -> dict[tuple[str, str], MeterChannel]:
    missing = []
    resolved: dict[tuple[str, str], MeterChannel] = {}
    for (nmi, suffix), m in meta.items():
        channel = MeterChannel.objects.filter(supply_point__nmi=nmi, suffix=suffix).first()
        if channel is None:
            missing.append(f"{nmi}:{suffix}")
        elif channel.interval_minutes != m.interval_minutes or channel.uom.lower() != m.uom.lower():
            raise Nem12Error(
                "channel_mismatch",
                f"{nmi}:{suffix} declares {m.uom}/{m.interval_minutes}min but channel "
                f"is {channel.uom}/{channel.interval_minutes}min",
            )
        else:
            resolved[(nmi, suffix)] = channel
    if missing:
        raise Nem12Error("unknown_nmi", f"unknown NMI/suffix: {', '.join(missing)}")
    return resolved


def _apply_selection(batch: IngestionBatch, affected: list[tuple[int, datetime]]) -> int:
    """Publish winners for affected intervals.

    Phase 1 evaluates candidates without locks — the read a racing publisher
    would have made. Phase 2 re-evaluates each interval under its
    CurrentInterval row lock (created on first publication via insert retry),
    so commits that landed mid-flight are seen before anything is written.
    """
    for channel_id, interval_end in affected:
        select_current(
            list(
                IntervalRecord.objects.filter(channel_id=channel_id, interval_end_utc=interval_end)
            )
        )

    accepted = 0
    for channel_id, interval_end in affected:
        for attempt in range(3):
            try:
                with transaction.atomic():
                    accepted += _publish_interval(batch, channel_id, interval_end)
                break
            except IntegrityError:
                if attempt == 2:
                    raise
    return accepted


def _publish_interval(batch: IngestionBatch, channel_id: int, interval_end: datetime) -> int:
    current = (
        CurrentInterval.objects.select_for_update()
        .filter(channel_id=channel_id, interval_end_utc=interval_end)
        .first()
    )
    candidates = list(
        IntervalRecord.objects.filter(channel_id=channel_id, interval_end_utc=interval_end)
    )
    winner, conflict = select_current(candidates)
    if conflict or winner is None:
        quarantine, _ = QuarantinedInterval.objects.get_or_create(
            channel_id=channel_id,
            interval_end_utc=interval_end,
            status=QuarantinedInterval.Status.OPEN,
            defaults={"detail": "equal-precedence conflicting values"},
        )
        best = max(precedence(c) for c in candidates)
        quarantine.candidate_records.add(*[c for c in candidates if precedence(c) == best])
        return 0

    if current is None:
        CurrentInterval.objects.create(
            channel_id=channel_id,
            interval_end_utc=interval_end,
            value=winner.value,
            quality=winner.quality,
            source_record=winner,
        )
    elif current.source_record_id != winner.id or current.value != winner.value:
        current.value = winner.value
        current.quality = winner.quality
        current.source_record = winner
        current.selection_version += 1
        current.save(
            update_fields=["value", "quality", "source_record", "selection_version", "updated_at"]
        )

    QuarantinedInterval.objects.filter(
        channel_id=channel_id,
        interval_end_utc=interval_end,
        status=QuarantinedInterval.Status.OPEN,
    ).update(status=QuarantinedInterval.Status.RESOLVED, resolved_at=timezone.now())
    return 1


class ResolutionError(ValueError):
    def __init__(self, code: str, detail: str):
        self.code = code
        super().__init__(detail)


def resolve_quarantine(
    quarantine_id: int, record_id: int, *, actor: str, reason: str
) -> QuarantinedInterval:
    """Approver-selected resolution for an open quarantine.

    The chosen candidate must be one of the recorded conflicting records.
    Its value is published as the current interval and the quarantine is
    closed with the actor and reason retained."""
    with transaction.atomic():
        quarantine = (
            QuarantinedInterval.objects.select_for_update()
            .filter(pk=quarantine_id, status=QuarantinedInterval.Status.OPEN)
            .first()
        )
        if quarantine is None:
            raise ResolutionError("not_found", "quarantine not found or already resolved")
        record = quarantine.candidate_records.filter(pk=record_id).first()
        if record is None:
            raise ResolutionError(
                "not_a_candidate", f"record {record_id} is not a quarantine candidate"
            )
        current = (
            CurrentInterval.objects.select_for_update()
            .filter(
                channel_id=quarantine.channel_id,
                interval_end_utc=quarantine.interval_end_utc,
            )
            .first()
        )
        if current is None:
            CurrentInterval.objects.create(
                channel_id=quarantine.channel_id,
                interval_end_utc=quarantine.interval_end_utc,
                value=record.value,
                quality=record.quality,
                source_record=record,
            )
        else:
            current.value = record.value
            current.quality = record.quality
            current.source_record = record
            current.selection_version += 1
            current.save(
                update_fields=[
                    "value",
                    "quality",
                    "source_record",
                    "selection_version",
                    "updated_at",
                ]
            )
        quarantine.status = QuarantinedInterval.Status.RESOLVED
        quarantine.resolved_at = timezone.now()
        quarantine.detail = f"{quarantine.detail} | resolved by {actor}: {reason}".strip(" |")
        quarantine.save(update_fields=["status", "resolved_at", "detail"])
    return quarantine


@dataclass(frozen=True)
class ChannelCoverage:
    channel_id: int
    expected: int
    selected: int
    quarantined: int

    @property
    def complete(self) -> bool:
        return self.selected == self.expected and self.quarantined == 0


def channel_coverage(channel: MeterChannel, start_date: date, end_date: date) -> ChannelCoverage:
    """Interval coverage for [start_date, end_date) NEM days.

    Billing calls this to reject incomplete coverage rather than silently
    rating partial data.
    """
    days = (end_date - start_date).days
    if days <= 0:
        raise ValueError("end_date must be after start_date")
    per_day = (24 * 60) // channel.interval_minutes
    start_utc = nem_interval_end_utc(start_date, 0, channel.interval_minutes)
    end_utc = nem_interval_end_utc(end_date, 0, channel.interval_minutes)
    selected = CurrentInterval.objects.filter(
        channel=channel, interval_end_utc__gt=start_utc, interval_end_utc__lte=end_utc
    ).count()
    quarantined = QuarantinedInterval.objects.filter(
        channel=channel,
        interval_end_utc__gt=start_utc,
        interval_end_utc__lte=end_utc,
        status=QuarantinedInterval.Status.OPEN,
    ).count()
    return ChannelCoverage(channel.id, days * per_day, selected, quarantined)
