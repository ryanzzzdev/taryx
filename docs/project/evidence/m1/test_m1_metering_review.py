"""Independent M1 probes. Run from repo root with uv run pytest -q <this file>."""

from datetime import date
from decimal import Decimal

import pytest

from taryx.core.accounts.models import Account, MeterChannel, SupplyPoint, TariffAgreement
from taryx.core.metering.ingestion import ingest_nem12_content
from taryx.core.metering.models import CurrentInterval, IngestionBatch, IntervalRecord
from taryx.core.pricing import services
from taryx.core.pricing.engine import RatingError
from taryx.territories.au_nem.tariffs import GST_RATE, POLICY_IDENTITY, TARIFFS

DAY = date(2026, 3, 2)
END = date(2026, 3, 3)
KWARGS = dict(tariffs=TARIFFS, gst_rate=GST_RATE, policy_identity=POLICY_IDENTITY)


def block(minutes=30, day="20260302"):
    return "\n".join(
        [
            f"200,4102000001,E1,,E1,NEM100,1000001,kWh,{minutes},",
            ",".join(
                ["300", day]
                + ["0.5"] * (1440 // minutes)
                + ["A", "", "", "20260301120000", "20260301120000"]
            ),
        ]
    )


def content(*blocks, sender="TARYX"):
    return (
        "100,NEM12,20260306120000," + sender + ",TARYX\n" + "\n".join(blocks) + "\n900\n"
    ).encode()


@pytest.fixture
def account(db):
    account = Account.objects.create(reference="REVIEW-M1", name="Review")
    supply = SupplyPoint.objects.create(nmi="4102000001", account=account)
    MeterChannel.objects.create(
        supply_point=supply, suffix="E1", direction="import", uom="kWh", interval_minutes=30
    )
    TariffAgreement.objects.create(
        account=account, tariff_code="T-FLAT", version=1, effective_from=date(2026, 1, 1)
    )
    return account


def test_mixed_interval_metadata_is_rejected_atomically(account):
    result = ingest_nem12_content(content(block(5), block(30, "20260303")), "mixed")
    assert result.batch.status == IngestionBatch.Status.REJECTED
    assert not IntervalRecord.objects.exists()
    assert not CurrentInterval.objects.exists()


def test_repeated_channel_day_has_explicit_outcome(account):
    result = ingest_nem12_content(content(block(), block()), "repeated-day")
    assert result.batch.status == IngestionBatch.Status.REJECTED
    assert not IntervalRecord.objects.exists()


def test_identical_revision_in_new_envelope_is_selection_noop(account):
    ingest_nem12_content(content(block()), "first")
    before = list(
        CurrentInterval.objects.order_by("interval_end_utc").values_list(
            "source_record_id", "selection_version"
        )
    )
    ingest_nem12_content(content(block(), sender="OTHER"), "same-revision")
    after = list(
        CurrentInterval.objects.order_by("interval_end_utc").values_list(
            "source_record_id", "selection_version"
        )
    )
    assert before == after


def test_rating_never_accepts_empty_snapshot_after_coverage_arrives(account, monkeypatch):
    original = services._gather_inputs

    def interleave(*args, **kwargs):
        snapshot = original(*args, **kwargs)
        # Deterministically place a committed publication between the two reads.
        ingest_nem12_content(content(block()), "arrives-after-snapshot")
        return snapshot

    monkeypatch.setattr(services, "_gather_inputs", interleave)
    try:
        run = services.rate_account(account, DAY, END, **KWARGS)
    except RatingError as error:
        assert error.code == "incomplete_coverage"
    else:
        # A coherent retried snapshot is also valid; supply-only is not.
        imports = run.lines.filter(element="import")
        assert sum((line.quantity for line in imports), Decimal(0)) == Decimal("24")
        assert len(run.input_snapshot["channels"][0]["records"]) == 48


def test_ordinary_replay_matches_independent_flat_total(account):
    ingest_nem12_content(content(block()), "normal")
    first = services.rate_account(account, DAY, END, **KWARGS)
    second = services.rate_account(account, DAY, END, **KWARGS)
    assert first.total == second.total == Decimal("9.13")
    assert first.input_digest == second.input_digest


def test_repeated_consistent_blocks_on_distinct_days_remain_supported(account):
    result = ingest_nem12_content(content(block(), block(day="20260303")), "two-days")
    assert result.batch.status == IngestionBatch.Status.PUBLISHED
    assert result.batch.record_count == 96
    assert CurrentInterval.objects.count() == 96


def test_equivalent_revision_keeps_digest_but_newer_revision_advances(account):
    original = content(block())
    ingest_nem12_content(original, "first")
    first = services.rate_account(account, DAY, END, **KWARGS)
    ingest_nem12_content(content(block(), sender="OTHER"), "equivalent")
    repeated = services.rate_account(account, DAY, END, **KWARGS)
    assert first.input_digest == repeated.input_digest
    assert set(CurrentInterval.objects.values_list("selection_version", flat=True)) == {1}

    newer = original.replace(b"20260301120000", b"20260302120000")
    ingest_nem12_content(newer, "newer-source-timestamp")
    revised = services.rate_account(account, DAY, END, **KWARGS)
    assert revised.input_digest != first.input_digest
    assert revised.total == first.total
    assert set(CurrentInterval.objects.values_list("selection_version", flat=True)) == {2}
