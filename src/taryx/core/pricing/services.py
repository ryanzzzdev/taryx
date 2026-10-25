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
from taryx.core.metering.models import CurrentInterval
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


def _input_digest(
    *,
    account: Account,
    period_start: date,
    period_end: date,
    agreements: list[AgreementSpan],
    tariffs: dict[str, TariffSpec],
    channels: list[tuple[MeterChannel, list]],
    gst_rate: Decimal,
    policy_identity: str,
) -> str:
    payload = {
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
                "import_bands": [[b.name, str(b.price)] for b in spec.import_bands],
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
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


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

    channels: list[tuple[MeterChannel, list[CurrentInterval]]] = []
    slices: list[ChannelSlice] = []
    for channel in MeterChannel.objects.filter(supply_point__account=account).order_by("id"):
        coverage = channel_coverage(channel, period_start, period_end)
        if not coverage.complete:
            raise RatingError(
                "incomplete_coverage",
                f"{channel}: {coverage.selected}/{coverage.expected} intervals, "
                f"{coverage.quarantined} quarantined",
            )
        start_utc = nem_interval_end_utc(period_start, 0, channel.interval_minutes)
        end_utc = nem_interval_end_utc(period_end, 0, channel.interval_minutes)
        rows = list(
            CurrentInterval.objects.filter(
                channel=channel,
                interval_end_utc__gt=start_utc,
                interval_end_utc__lte=end_utc,
            )
            .select_related("source_record")
            .order_by("interval_end_utc")
        )
        channels.append((channel, rows))
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

    agreements = [
        AgreementSpan(
            agreement_id=a.id,
            tariff_code=a.tariff_code,
            version=a.version,
            effective_from=a.effective_from,
            effective_to=a.effective_to,
        )
        for a in account.tariff_agreements.all()
    ]

    calc = rate(
        days=days,
        agreements=agreements,
        tariffs=tariffs,
        channels=slices,
        gst_rate=gst_rate,
    )

    digest = _input_digest(
        account=account,
        period_start=period_start,
        period_end=period_end,
        agreements=agreements,
        tariffs=tariffs,
        channels=channels,
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
            input_digest=digest,
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
