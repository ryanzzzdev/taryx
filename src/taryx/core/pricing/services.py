"""Rating orchestration: gather immutable inputs, pin them, rate, persist.

Coverage, agreement resolution and error policy live here; the arithmetic
in engine.py stays pure and independently testable. Tariff specs are
injected by the caller (territory/client policy packages, wired in
composition) so core never imports outer layers.
"""

import hashlib
import json
from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction

from taryx.core.accounts.models import Account, MeterChannel
from taryx.core.metering.ingestion import channel_coverage
from taryx.core.metering.models import CurrentInterval, QuarantinedInterval
from taryx.core.metering.nem_time import nem_interval_end_utc, nem_local
from taryx.core.pricing.engine import (
    ENGINE_VERSION,
    AgreementSpan,
    ChannelSlice,
    IntervalQty,
    RatingError,
    rate,
)
from taryx.core.pricing.models import RatingLine, RatingRun
from taryx.core.pricing.tariffs import TariffSpec


def _input_payload(
    *,
    account: Account,
    period_start: date,
    period_end: date,
    agreements: list[AgreementSpan],
    tariffs: dict[str, TariffSpec],
    channels: list[tuple[MeterChannel, list]],
    quarantines: list[QuarantinedInterval],
    gst_rate: Decimal,
    policy_identity: str,
) -> dict:
    """The exact inputs a rating consumes — hashed into input_digest and
    retained verbatim on the run so historical calculations stay
    reconstructible even if referenced metadata rows later change."""
    return {
        "account": account.reference,
        "period": [period_start.isoformat(), period_end.isoformat()],
        "engine_version": ENGINE_VERSION,
        "policy_identity": policy_identity,
        "gst_rate": str(gst_rate),
        "agreements": [
            {
                "id": a.agreement_id,
                "tariff_code": a.tariff_code,
                "version": a.version,
                "effective_from": a.effective_from.isoformat(),
                "effective_to": a.effective_to.isoformat() if a.effective_to else None,
            }
            for a in sorted(agreements, key=lambda a: a.agreement_id)
        ],
        "tariffs": {
            code: {
                "version": spec.version,
                "supply_per_day": str(spec.supply_per_day),
                "import_bands": [
                    [
                        b.name,
                        str(b.price),
                        ([b.window[0].isoformat(), b.window[1].isoformat()] if b.window else None),
                    ]
                    for b in spec.import_bands
                ],
                "export_credit_per_kwh": (
                    str(spec.export_credit_per_kwh) if spec.export_credit_per_kwh else None
                ),
            }
            for code, spec in sorted(tariffs.items())
        },
        "channels": [
            {
                "channel_id": channel.id,
                "suffix": channel.suffix,
                "direction": channel.direction,
                "records": [
                    [
                        row.interval_end_utc.isoformat(),
                        str(row.value),
                        row.quality,
                        row.source_record_id,
                    ]
                    for row in rows
                ],
            }
            for channel, rows in sorted(channels, key=lambda c: c[0].id)
        ],
        "quarantines": [
            [q.id, q.channel_id, q.interval_end_utc.isoformat()]
            for q in sorted(quarantines, key=lambda q: q.id)
        ],
    }


def _input_digest(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _gather_inputs(
    account: Account, period_start: date, period_end: date, *, lock: bool = False
) -> tuple[
    list[AgreementSpan],
    list[tuple[MeterChannel, list[CurrentInterval]]],
    list[QuarantinedInterval],
]:
    """Selected interval rows, open quarantines and agreement spans pinning
    a rating period.

    With lock=True every row feeding the digest is locked FOR UPDATE —
    billing holds those locks from final validation through commit so no
    input-changing writer can interleave. Mutating paths (interval
    publication, quarantine resolution) take the account row lock first,
    which is what prevents a concurrent *insert* of a new quarantine from
    slipping between validation and commit.
    """
    channel_rows: list[tuple[MeterChannel, list[CurrentInterval]]] = []
    quarantines: list[QuarantinedInterval] = []
    for channel in MeterChannel.objects.filter(supply_point__account=account).order_by("id"):
        start_utc = nem_interval_end_utc(period_start, 0, channel.interval_minutes)
        end_utc = nem_interval_end_utc(period_end, 0, channel.interval_minutes)
        interval_qs = CurrentInterval.objects.filter(
            channel=channel,
            interval_end_utc__gt=start_utc,
            interval_end_utc__lte=end_utc,
        ).select_related("source_record")
        if lock:
            interval_qs = interval_qs.select_for_update(of=("self",))
        rows = list(interval_qs.order_by("interval_end_utc"))
        channel_rows.append((channel, rows))
        quarantine_qs = QuarantinedInterval.objects.filter(
            channel=channel,
            interval_end_utc__gt=start_utc,
            interval_end_utc__lte=end_utc,
            status=QuarantinedInterval.Status.OPEN,
        )
        if lock:
            quarantine_qs = quarantine_qs.select_for_update()
        quarantines.extend(quarantine_qs.order_by("id"))
    agreement_qs = account.tariff_agreements.all()
    if lock:
        agreement_qs = agreement_qs.select_for_update()
    agreements = [
        AgreementSpan(
            agreement_id=a.id,
            tariff_code=a.tariff_code,
            version=a.version,
            effective_from=a.effective_from,
            effective_to=a.effective_to,
        )
        for a in agreement_qs
    ]
    return agreements, channel_rows, quarantines


def lock_inputs(account: Account, period_start: date, period_end: date) -> None:
    """Shared revision protocol for input-changing writers.

    Acquires, in order, the account row lock then every row feeding this
    period's input digest. Callers must hold these locks from the final
    digest validation through transaction commit; publishers and
    quarantine resolution acquire the same account lock first so any
    input change either lands before (and is re-validated) or waits
    until the financial transaction commits.
    """
    Account.objects.select_for_update().filter(pk=account.pk).exists()
    _gather_inputs(account, period_start, period_end, lock=True)


def compute_input_digest(
    account: Account,
    period_start: date,
    period_end: date,
    *,
    tariffs: dict[str, TariffSpec],
    gst_rate: Decimal,
    policy_identity: str,
) -> str:
    """Digest of the inputs a rating over this period would consume now."""
    agreements, channel_rows, quarantines = _gather_inputs(account, period_start, period_end)
    return _input_digest(
        _input_payload(
            account=account,
            period_start=period_start,
            period_end=period_end,
            agreements=agreements,
            tariffs=tariffs,
            channels=channel_rows,
            quarantines=quarantines,
            gst_rate=gst_rate,
            policy_identity=policy_identity,
        )
    )


def rate_account(
    account: Account,
    period_start: date,
    period_end: date,
    *,
    tariffs: dict[str, TariffSpec],
    gst_rate: Decimal,
    policy_identity: str,
) -> RatingRun:
    """Rate [period_start, period_end) NEM days and persist the pinned run."""
    days = [period_start + timedelta(days=i) for i in range((period_end - period_start).days)]
    if not days:
        raise RatingError("empty_period", "period must cover at least one day")

    agreements, channel_rows, quarantines = _gather_inputs(account, period_start, period_end)

    slices: list[ChannelSlice] = []
    for channel, rows in channel_rows:
        coverage = channel_coverage(channel, period_start, period_end)
        if not coverage.complete:
            raise RatingError(
                "incomplete_coverage",
                f"{channel}: {coverage.selected}/{coverage.expected} intervals, "
                f"{coverage.quarantined} quarantined",
            )
        slices.append(
            ChannelSlice(
                channel_id=channel.id,
                suffix=channel.suffix,
                direction=channel.direction,
                intervals=tuple(
                    IntervalQty(
                        day=row.source_record.interval_date,
                        end_tod=nem_local(row.interval_end_utc).time(),
                        value=row.value,
                    )
                    for row in rows
                ),
            )
        )

    calc = rate(
        days=days,
        agreements=agreements,
        tariffs=tariffs,
        channels=slices,
        gst_rate=gst_rate,
    )

    payload = _input_payload(
        account=account,
        period_start=period_start,
        period_end=period_end,
        agreements=agreements,
        tariffs=tariffs,
        channels=channel_rows,
        quarantines=quarantines,
        gst_rate=gst_rate,
        policy_identity=policy_identity,
    )

    with transaction.atomic():
        run = RatingRun.objects.create(
            account=account,
            period_start=period_start,
            period_end=period_end,
            engine_version=ENGINE_VERSION,
            policy_identity=policy_identity,
            input_digest=_input_digest(payload),
            input_snapshot=payload,
            net=calc.net,
            gst=calc.gst,
            total=calc.total,
        )
        RatingLine.objects.bulk_create(
            RatingLine(
                run=run,
                sequence=index,
                agreement_id=line.agreement_id,
                tariff_code=line.tariff_code,
                segment_from=line.segment_from,
                segment_to=line.segment_to,
                element=line.element,
                band=line.band,
                quantity=line.quantity,
                unit=line.unit,
                rate=line.rate,
                amount=line.amount,
                gst=line.gst,
                basis=line.basis,
            )
            for index, line in enumerate(calc.lines, start=1)
        )
    return run
