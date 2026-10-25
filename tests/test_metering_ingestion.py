import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from taryx.core.accounts.models import MeterChannel
from taryx.core.accounts.seed import seed_demo_data
from taryx.core.metering.ingestion import channel_coverage, ingest_nem12_content
from taryx.core.metering.models import (
    CurrentInterval,
    IntervalRecord,
    QuarantinedInterval,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "nem12"
EXPECTED = json.loads((FIXTURES / "expected.json").read_text())


def load(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


@pytest.fixture
def seeded(db):
    return seed_demo_data()


def channel(suffix: str) -> MeterChannel:
    return MeterChannel.objects.get(supply_point__nmi="4102000001", suffix=suffix)


def current_value(suffix: str, interval_number: int, day: date) -> Decimal:
    from taryx.core.metering.nem_time import nem_interval_end_utc

    return CurrentInterval.objects.get(
        channel=channel(suffix),
        interval_end_utc=nem_interval_end_utc(day, interval_number, 30),
    ).value


@pytest.mark.django_db
def test_valid_batch_publishes_and_selects(seeded):
    result = ingest_nem12_content(load("day1_base.nem12"), "day1_base.nem12")
    batch = result.batch
    expected = EXPECTED["day1_base"]
    assert batch.status == "published"
    assert batch.record_count == expected["records"]
    for suffix, key in (("E1", "e1"), ("B1", "b1")):
        rows = CurrentInterval.objects.filter(channel=channel(suffix))
        assert rows.count() == expected[key]["count"]
        assert {str(r.value) for r in rows} == {expected[key]["value"]}
        assert {r.quality for r in rows} == {expected[key]["quality"]}
    assert IntervalRecord.objects.count() == expected["records"]


@pytest.mark.django_db
def test_duplicate_batch_is_inspectable_noop(seeded):
    ingest_nem12_content(load("day1_base.nem12"), "day1_base.nem12")
    before = IntervalRecord.objects.count()
    dup = ingest_nem12_content(load("day1_base.nem12"), "day1_base-copy.nem12").batch
    assert dup.status == "duplicate"
    assert dup.duplicate_of.status == "published"
    assert IntervalRecord.objects.count() == before


@pytest.mark.django_db
def test_revision_selection_ignores_arrival_order(seeded):
    ingest_nem12_content(load("day2_act.nem12"), "day2_act.nem12")
    ingest_nem12_content(load("day2_est.nem12"), "day2_est.nem12")
    e1 = channel("E1")
    assert (
        CurrentInterval.objects.get(
            channel=e1,
            interval_end_utc=datetime(2026, 3, 2, 15, 30, tzinfo=UTC),
        ).quality
        == EXPECTED["day2_est_then_act"]["e1_quality"]
    )
    # Now feed the same day the other way: E first, then A on a fresh day.
    ingest_nem12_content(load("day2_est.nem12"), "day2_est-again.nem12")  # duplicate -> noop


@pytest.mark.django_db
def test_estimated_then_actual_replaces(seeded):
    ingest_nem12_content(load("day2_est.nem12"), "day2_est.nem12")
    assert {r.quality for r in CurrentInterval.objects.all()} == {"E"}
    ingest_nem12_content(load("day2_act.nem12"), "day2_act.nem12")
    qualities = {r.quality for r in CurrentInterval.objects.all()}
    assert qualities == {"A"}
    assert all(
        str(r.value) == EXPECTED["day2_est_then_act"]["e1_value"]
        for r in CurrentInterval.objects.filter(channel=channel("E1"))
    )


@pytest.mark.django_db
def test_substitute_then_final(seeded):
    ingest_nem12_content(load("day3_sub.nem12"), "day3_sub.nem12")
    assert {r.quality for r in CurrentInterval.objects.all()} == {"S"}
    ingest_nem12_content(load("day3_final.nem12"), "day3_final.nem12")
    rows = CurrentInterval.objects.all()
    assert {r.quality for r in rows} == {EXPECTED["day3_sub_then_final"]["e1_quality"]}
    assert {str(r.value) for r in rows} == {EXPECTED["day3_sub_then_final"]["e1_value"]}


@pytest.mark.django_db
def test_successive_revisions_preserve_history(seeded):
    ingest_nem12_content(load("day1_base.nem12"), "day1_base.nem12")
    day = date(2026, 3, 2)
    assert str(current_value("E1", 20, day)) == "0.500000"
    ingest_nem12_content(load("day1_rev1.nem12"), "day1_rev1.nem12")
    assert str(current_value("E1", 20, day)) == EXPECTED["day1_revisions"]["after_rev1_interval20"]
    ingest_nem12_content(load("day1_rev2.nem12"), "day1_rev2.nem12")
    assert str(current_value("E1", 20, day)) == EXPECTED["day1_revisions"]["after_rev2_interval20"]
    assert str(current_value("E1", 5, day)) == "0.500000"
    records = IntervalRecord.objects.filter(
        channel=channel("E1"), interval_number=20, interval_date=day
    )
    assert records.count() == 3  # all revisions retained


@pytest.mark.django_db
def test_equal_precedence_conflict_quarantines(seeded):
    ingest_nem12_content(load("day1_rev2.nem12"), "day1_rev2.nem12")
    ingest_nem12_content(load("day1_conflict.nem12"), "day1_conflict.nem12")
    quarantines = QuarantinedInterval.objects.filter(status="open")
    assert quarantines.count() == EXPECTED["day1_conflict"]["open_quarantines"]
    assert (
        str(current_value("E1", 20, date(2026, 3, 2)))
        == EXPECTED["day1_conflict"]["current_value_unchanged"]
    )


@pytest.mark.django_db
def test_variable_quality_day_uses_400_records(seeded):
    result = ingest_nem12_content(load("day5_var.nem12"), "day5_var.nem12")
    assert result.batch.status == EXPECTED["day5_var"]["status"]
    expected = EXPECTED["day5_var"]["qualities"]
    for quality, count in expected.items():
        assert (
            CurrentInterval.objects.filter(channel=channel("E1"), quality=quality).count() == count
        )


@pytest.mark.django_db
@pytest.mark.parametrize(
    "filename,code",
    sorted(EXPECTED["rejections"].items()),
)
def test_invalid_inputs_rejected_without_partial_data(seeded, filename, code):
    result = ingest_nem12_content(load(f"{filename}.nem12"), filename)
    batch = result.batch
    assert batch.status == "rejected"
    assert batch.error_code == code
    assert IntervalRecord.objects.count() == 0
    assert CurrentInterval.objects.count() == 0


@pytest.mark.django_db
def test_coverage_reports_gaps_and_completion(seeded):
    ingest_nem12_content(load("day1_base.nem12"), "day1_base.nem12")
    ingest_nem12_content(load("day2_act.nem12"), "day2_act.nem12")
    e1 = channel("E1")
    cov = channel_coverage(e1, date(2026, 3, 2), date(2026, 3, 4))
    assert cov.expected == 96 and cov.selected == 96 and cov.complete

    partial = channel_coverage(e1, date(2026, 3, 2), date(2026, 3, 6))
    assert partial.expected == 192 and partial.selected == 96
    assert not partial.complete

    quarantine_cov = channel_coverage(e1, date(2026, 3, 2), date(2026, 3, 4))
    assert quarantine_cov.quarantined == 0


@pytest.mark.django_db
def test_quarantined_interval_blocks_coverage(seeded):
    ingest_nem12_content(load("day1_rev2.nem12"), "day1_rev2.nem12")
    ingest_nem12_content(load("day1_conflict.nem12"), "day1_conflict.nem12")
    cov = channel_coverage(channel("E1"), date(2026, 3, 2), date(2026, 3, 3))
    assert cov.quarantined == 1
    assert not cov.complete
