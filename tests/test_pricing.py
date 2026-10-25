"""Rating tests against the independent reference cases (RC-01..06, RC-08).

Expected amounts are hand-computed in docs/project/features/rating-reference-cases.md
— never derived from the engine.
"""

import hashlib
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from django.db import Error as DbError
from django.db import transaction

from taryx.core.accounts.models import (
    Account,
    MeterChannel,
    SupplyPoint,
    TariffAgreement,
)
from taryx.core.accounts.seed import seed_demo_data
from taryx.core.metering.ingestion import ingest_nem12_content
from taryx.core.metering.models import IntervalRecord
from taryx.core.pricing.engine import RatingError
from taryx.core.pricing.models import RatingLine, RatingRun
from taryx.core.pricing.services import compute_input_digest, rate_account
from taryx.territories.au_nem.tariffs import GST_RATE, POLICY_IDENTITY, TARIFFS

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "nem12"

KWARGS = {"tariffs": TARIFFS, "gst_rate": GST_RATE, "policy_identity": POLICY_IDENTITY}


def load(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def make_account(
    channels: list[tuple[str, str]],
    agreements: list[tuple[str, date, date | None]],
    reference: str = "ACC-T1",
    nmi: str = "4102000001",
) -> Account:
    account = Account.objects.create(reference=reference, name="Test Retailer")
    supply = SupplyPoint.objects.create(nmi=nmi, account=account)
    for suffix, direction in channels:
        MeterChannel.objects.create(
            supply_point=supply,
            suffix=suffix,
            direction=direction,
            uom="kWh",
            interval_minutes=30,
        )
    for version, (tariff_code, start, end) in enumerate(agreements, start=1):
        TariffAgreement.objects.create(
            account=account,
            tariff_code=tariff_code,
            effective_from=start,
            effective_to=end,
            version=version,
        )
    return account


def line_for(run, element, band=None, segment_from=None):
    matches = [
        item
        for item in run.lines.all()
        if item.element == element
        and (band is None or item.band == band)
        and (segment_from is None or item.segment_from == segment_from)
    ]
    assert len(matches) == 1, [str(item) for item in run.lines.all()]
    return matches[0]


@pytest.mark.django_db
def test_rc01_flat_one_day():
    account = make_account([("E1", "import")], [("T-FLAT", date(2026, 1, 1), None)])
    ingest_nem12_content(load("e1_flat.nem12"), "e1_flat.nem12")
    run = rate_account(account, date(2026, 3, 2), date(2026, 3, 3), **KWARGS)
    imp = line_for(run, "import")
    assert (imp.quantity, imp.rate, imp.amount, imp.gst) == (
        Decimal("24.0"),
        Decimal("0.30"),
        Decimal("7.20"),
        Decimal("0.72"),
    )
    supply = line_for(run, "supply")
    assert (supply.quantity, supply.amount, supply.gst) == (
        Decimal("1"),
        Decimal("1.10"),
        Decimal("0.11"),
    )
    assert (run.net, run.gst, run.total) == (
        Decimal("8.30"),
        Decimal("0.83"),
        Decimal("9.13"),
    )


@pytest.mark.django_db
def test_rc02_tou_split():
    account = make_account([("E1", "import")], [("T-TOU", date(2026, 1, 1), None)])
    ingest_nem12_content(load("e1_flat.nem12"), "e1_flat.nem12")
    run = rate_account(account, date(2026, 3, 2), date(2026, 3, 3), **KWARGS)
    peak = line_for(run, "import", band="peak")
    assert (peak.quantity, peak.amount, peak.gst) == (
        Decimal("15.0"),  # 30 intervals ending (07:00, 22:00]
        Decimal("6.00"),
        Decimal("0.60"),
    )
    offpeak = line_for(run, "import", band="offpeak")
    assert (offpeak.quantity, offpeak.amount, offpeak.gst) == (
        Decimal("9.0"),  # 18 intervals; ending 07:00 is off-peak
        Decimal("1.80"),
        Decimal("0.18"),
    )
    assert (run.net, run.gst, run.total) == (
        Decimal("8.90"),
        Decimal("0.89"),
        Decimal("9.79"),
    )


@pytest.mark.django_db
def test_rc03_export_credit_seeded_account():
    seed_demo_data()
    ingest_nem12_content(load("day1_base.nem12"), "day1_base.nem12")
    account = Account.objects.get(reference="ACC-001")
    run = rate_account(account, date(2026, 3, 2), date(2026, 3, 3), **KWARGS)
    credit = line_for(run, "export_credit")
    assert (credit.quantity, credit.amount, credit.gst) == (
        Decimal("9.6"),
        Decimal("-0.48"),
        Decimal("0"),
    )
    assert (run.net, run.gst, run.total) == (
        Decimal("7.82"),
        Decimal("0.83"),
        Decimal("8.65"),
    )


@pytest.mark.django_db
def test_rc04_tariff_boundary_mid_period():
    account = make_account(
        [("E1", "import")],
        [
            ("T-FLAT", date(2026, 1, 1), date(2026, 1, 15)),
            ("T-FLAT-V2", date(2026, 1, 15), None),
        ],
    )
    ingest_nem12_content(load("e1_flat_jan.nem12"), "e1_flat_jan.nem12")
    run = rate_account(account, date(2026, 1, 1), date(2026, 2, 1), **KWARGS)
    v1 = line_for(run, "import", segment_from=date(2026, 1, 1))
    assert (v1.quantity, v1.amount, v1.gst) == (
        Decimal("336.0"),  # 14 days x 24 kWh
        Decimal("100.80"),
        Decimal("10.08"),
    )
    v2 = line_for(run, "import", segment_from=date(2026, 1, 15))
    assert (v2.quantity, v2.amount, v2.gst) == (
        Decimal("408.0"),  # 17 days x 24 kWh
        Decimal("142.80"),
        Decimal("14.28"),
    )
    assert (run.net, run.gst, run.total) == (
        Decimal("277.70"),
        Decimal("27.77"),
        Decimal("305.47"),
    )


@pytest.mark.django_db
def test_rc05_leap_month_february_2028():
    account = make_account([("E1", "import")], [("T-FLAT", date(2028, 2, 1), None)])
    ingest_nem12_content(load("e1_flat_feb2028.nem12"), "e1_flat_feb2028.nem12")
    run = rate_account(account, date(2028, 2, 1), date(2028, 3, 1), **KWARGS)
    assert (run.net, run.gst, run.total) == (
        Decimal("240.70"),
        Decimal("24.07"),
        Decimal("264.77"),
    )


@pytest.mark.django_db
def test_rc06_dst_transition_is_full_nem_day():
    account = make_account([("E1", "import")], [("T-FLAT", date(2026, 10, 1), None)])
    ingest_nem12_content(load("e1_flat_dst.nem12"), "e1_flat_dst.nem12")
    run = rate_account(account, date(2026, 10, 4), date(2026, 10, 5), **KWARGS)
    assert run.total == Decimal("9.13")
    assert line_for(run, "import").quantity == Decimal("24.0")


@pytest.mark.django_db
def test_incomplete_coverage_blocks_rating():
    account = make_account([("E1", "import")], [("T-FLAT", date(2026, 1, 1), None)])
    ingest_nem12_content(load("e1_flat.nem12"), "e1_flat.nem12")
    with pytest.raises(RatingError) as exc:
        rate_account(account, date(2026, 3, 2), date(2026, 3, 4), **KWARGS)
    assert exc.value.code == "incomplete_coverage"


@pytest.mark.django_db
def test_quarantine_blocks_rating():
    seed_demo_data()
    ingest_nem12_content(load("day1_rev2.nem12"), "day1_rev2.nem12")
    ingest_nem12_content(load("day1_conflict.nem12"), "day1_conflict.nem12")
    account = Account.objects.get(reference="ACC-001")
    with pytest.raises(RatingError) as exc:
        rate_account(account, date(2026, 3, 2), date(2026, 3, 3), **KWARGS)
    assert exc.value.code == "incomplete_coverage"


@pytest.mark.django_db
def test_missing_agreement_is_explicit_error():
    account = make_account([("E1", "import")], [("T-FLAT", date(2026, 3, 3), None)])
    ingest_nem12_content(load("e1_flat.nem12"), "e1_flat.nem12")
    with pytest.raises(RatingError) as exc:
        rate_account(account, date(2026, 3, 2), date(2026, 3, 3), **KWARGS)
    assert exc.value.code == "missing_agreement"


@pytest.mark.django_db
def test_overlapping_agreements_are_explicit_error():
    account = make_account(
        [("E1", "import")],
        [
            ("T-FLAT", date(2026, 1, 1), None),
            ("T-TOU", date(2026, 2, 1), None),
        ],
    )
    ingest_nem12_content(load("e1_flat.nem12"), "e1_flat.nem12")
    with pytest.raises(RatingError) as exc:
        rate_account(account, date(2026, 3, 2), date(2026, 3, 3), **KWARGS)
    assert exc.value.code == "overlapping_agreements"


@pytest.mark.django_db
def test_unknown_tariff_code_is_explicit_error():
    account = make_account([("E1", "import")], [("T-NOPE", date(2026, 1, 1), None)])
    ingest_nem12_content(load("e1_flat.nem12"), "e1_flat.nem12")
    with pytest.raises(RatingError) as exc:
        rate_account(account, date(2026, 3, 2), date(2026, 3, 3), **KWARGS)
    assert exc.value.code == "unknown_tariff"


@pytest.mark.django_db
def test_replay_is_deterministic():
    account = make_account([("E1", "import")], [("T-FLAT", date(2026, 1, 1), None)])
    ingest_nem12_content(load("e1_flat.nem12"), "e1_flat.nem12")
    run1 = rate_account(account, date(2026, 3, 2), date(2026, 3, 3), **KWARGS)
    run2 = rate_account(account, date(2026, 3, 2), date(2026, 3, 3), **KWARGS)
    assert run1.input_digest == run2.input_digest
    assert [item.basis for item in run1.lines.all()] == [item.basis for item in run2.lines.all()]
    assert [
        (
            item.element,
            item.band,
            str(item.quantity),
            str(item.rate),
            str(item.amount),
            str(item.gst),
        )
        for item in run1.lines.all()
    ] == [
        (
            item.element,
            item.band,
            str(item.quantity),
            str(item.rate),
            str(item.amount),
            str(item.gst),
        )
        for item in run2.lines.all()
    ]


@pytest.mark.django_db
def test_published_rating_evidence_is_immutable():
    """Rating runs, lines and their source records are calculation
    evidence — the database rejects mutation, not just convention."""
    account = make_account([("E1", "import")], [("T-FLAT", date(2026, 1, 1), None)])
    ingest_nem12_content(load("e1_flat.nem12"), "e1_flat.nem12")
    run = rate_account(account, date(2026, 3, 2), date(2026, 3, 3), **KWARGS)
    with pytest.raises(DbError), transaction.atomic():
        RatingLine.objects.filter(run=run, element="import").update(quantity=999, amount=999)
    with pytest.raises(DbError), transaction.atomic():
        RatingRun.objects.filter(pk=run.pk).update(total=0)
    with pytest.raises(DbError), transaction.atomic():
        IntervalRecord.objects.filter(channel__supply_point__account=account).update(value=0)


@pytest.mark.django_db
def test_input_snapshot_reconstructs_historical_run():
    """After newer inputs exist, the stored snapshot still pins the run's
    exact selections and hashes back to its digest."""
    account = make_account([("E1", "import")], [("T-FLAT", date(2026, 1, 1), None)])
    ingest_nem12_content(load("e1_flat.nem12"), "e1_flat.nem12")
    run = rate_account(account, date(2026, 3, 2), date(2026, 3, 3), **KWARGS)
    pinned = [row[3] for ch in run.input_snapshot["channels"] for row in ch["records"]]

    # A revision with newer timestamps changes the current selection;
    # the run's snapshot must not.
    revised = load("e1_flat.nem12").decode().replace("20260301120000", "20260310120000")
    ingest_nem12_content(revised.encode(), "e1_flat_rev.nem12")
    current = compute_input_digest(account, date(2026, 3, 2), date(2026, 3, 3), **KWARGS)
    assert current != run.input_digest
    assert [row[3] for ch in run.input_snapshot["channels"] for row in ch["records"]] == pinned
    assert (
        hashlib.sha256(json.dumps(run.input_snapshot, sort_keys=True).encode()).hexdigest()
        == run.input_digest
    )
