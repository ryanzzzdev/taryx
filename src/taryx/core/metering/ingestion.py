"""Batch ingestion: stage, validate and publish NEM12 data atomically.

A batch either publishes fully (records stored, current selection updated)
or is rejected with an error code — never a partially visible dataset.
"""

import hashlib
from dataclasses import dataclass
from datetime import date, datetime

from django.db import transaction
from django.db.utils import IntegrityError

from taryx.core.accounts.models import MeterChannel
from taryx.core.metering.models import (
    CurrentInterval,
    IngestionBatch,
    IntervalRecord,
    QuarantinedInterval,
)
from taryx.core.metering.nem12 import ChannelData, ChannelMeta, Nem12Error, parse_nem12
from taryx.core.metering.nem_time import nem_interval_end_utc
from taryx.core.metering.selection import select_current


@dataclass(frozen=True)
class IngestResult:
    batch: IngestionBatch


def ingest_nem12_content(content: bytes, source_name: str) -> IngestResult:
    content_hash = hashlib.sha256(content).hexdigest()
    existing = IngestionBatch.objects.exclude(status=IngestionBatch.Status.DUPLICATE).filter(
        content_sha256=content_hash
    )
    if existing.exists():
        original = existing.get()
        batch = IngestionBatch.objects.create(
            source_name=source_name,
            content_sha256=content_hash,
            status=IngestionBatch.Status.DUPLICATE,
            duplicate_of=original,
        )
        return IngestResult(batch)

    try:
        meta, channels = parse_nem12(content.decode("utf-8"))
        batch = _publish(content_hash, source_name, meta, channels)
    except Nem12Error as exc:
        batch = IngestionBatch.objects.create(
            source_name=source_name,
            content_sha256=content_hash,
            status=IngestionBatch.Status.REJECTED,
            error_code=exc.code,
            error_detail=str(exc),
        )
    return IngestResult(batch)


def _publish(
    content_hash: str,
    source_name: str,
    meta: dict[tuple[str, str], ChannelMeta],
    channels: list[ChannelData],
) -> IngestionBatch:
    channel_rows = _resolve_channels(meta)
    with transaction.atomic():
        try:
            batch = IngestionBatch.objects.create(
                source_name=source_name,
                content_sha256=content_hash,
                status=IngestionBatch.Status.PUBLISHED,
            )
        except IntegrityError:
            original = IngestionBatch.objects.get(
                content_sha256=content_hash, status=IngestionBatch.Status.PUBLISHED
            )
            return IngestionBatch.objects.create(
                source_name=source_name,
                content_sha256=content_hash,
                status=IngestionBatch.Status.DUPLICATE,
                duplicate_of=original,
            )

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
                            reason_code=item.reason_code,
                            update_dt=item.update_dt,
                            msats_load_dt=item.msats_load_dt,
                            row_number=day.row_number,
                        )
                    )
        IntervalRecord.objects.bulk_create(records)

        affected = {(r.channel_id, r.interval_end_utc) for r in records}
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


def _apply_selection(batch: IngestionBatch, affected: set[tuple[int, datetime]]) -> int:
    accepted = 0
    for channel_id, interval_end in affected:
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
            quarantine.candidate_records.add(*[c for c in candidates if c.batch_id == batch.id])
            continue
        current, created = CurrentInterval.objects.get_or_create(
            channel_id=channel_id,
            interval_end_utc=interval_end,
            defaults={
                "value": winner.value,
                "quality": winner.quality,
                "source_record": winner,
            },
        )
        if not created and (current.source_record_id != winner.id or current.value != winner.value):
            current.value = winner.value
            current.quality = winner.quality
            current.source_record = winner
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
        accepted += 1
    return accepted


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
