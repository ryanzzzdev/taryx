import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from threading import Barrier, Event, current_thread
from unittest.mock import patch

import pytest
from django.db import close_old_connections

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
def test_quality_method_codes_retained(seeded):
    ingest_nem12_content(load("day2_est.nem12"), "day2_est.nem12")
    est = IntervalRecord.objects.filter(channel=channel("E1")).first()
    assert est.quality == "E"
    assert est.method_code == EXPECTED["day2_est_then_act"]["e1_est_method"]
    ingest_nem12_content(load("day2_act.nem12"), "day2_act.nem12")
    act = IntervalRecord.objects.filter(channel=channel("E1"), quality="A").first()
    assert act.method_code is None


@pytest.mark.django_db
def test_actual_day_with_400_reason_codes(seeded):
    result = ingest_nem12_content(load("day6_a_reasons.nem12"), "day6_a_reasons.nem12")
    assert result.batch.status == EXPECTED["day6_a_reasons"]["status"]
    assert {r.quality for r in CurrentInterval.objects.all()} == {"A"}
    for code, count in EXPECTED["day6_a_reasons"]["reason_counts"].items():
        assert (
            IntervalRecord.objects.filter(channel=channel("E1"), reason_code=code).count() == count
        )


@pytest.mark.django_db
def test_newer_revision_resolves_obsolete_quarantine(seeded):
    ingest_nem12_content(load("day1_rev2.nem12"), "day1_rev2.nem12")
    ingest_nem12_content(load("day1_conflict.nem12"), "day1_conflict.nem12")
    assert QuarantinedInterval.objects.filter(status="open").count() == 1
    text = (FIXTURES / "day1_rev2.nem12").read_text().replace("20260304120000", "20260310120000")
    ingest_nem12_content(text.encode(), "day1_rev3.nem12")
    quarantine = QuarantinedInterval.objects.get()
    assert quarantine.status == "resolved"
    assert quarantine.resolved_at is not None
    assert quarantine.candidate_records.count() == 2  # both rivals kept
    cov = channel_coverage(channel("E1"), date(2026, 3, 2), date(2026, 3, 3))
    assert cov.complete


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


@pytest.mark.django_db(transaction=True)
def test_concurrent_duplicate_ingest_is_single_winner():
    from taryx.core.metering import ingestion

    seed_demo_data()
    barrier = Barrier(2)
    original = ingestion.parse_nem12

    def parse(text):
        parsed = original(text)
        barrier.wait(timeout=10)
        return parsed

    def run():
        close_old_connections()
        try:
            return ingest_nem12_content(load("day1_base.nem12"), "concurrent").batch.status
        finally:
            close_old_connections()

    with (
        patch.object(ingestion, "parse_nem12", parse),
        ThreadPoolExecutor(max_workers=2) as pool,
    ):
        outcomes = sorted(f.result(timeout=30) for f in [pool.submit(run) for _ in range(2)])
    assert outcomes == ["duplicate", "published"]


@pytest.mark.django_db(transaction=True)
def test_concurrent_revisions_keep_newest_current():
    from taryx.core.metering import ingestion

    seed_demo_data()
    ingest_nem12_content(load("day1_base.nem12"), "day1_base.nem12")
    low_read, high_done = Event(), Event()
    original = ingestion.select_current

    def revision(value: str, stamp: str) -> bytes:
        lines = (FIXTURES / "day1_rev1.nem12").read_text().splitlines()
        lines[2] = f"300,20260302,{','.join([value] * 48)},A,,,{stamp},{stamp}"
        return ("\n".join(lines) + "\n").encode()

    def select(records):
        result = original(records)
        if current_thread().name.endswith("_0") and not low_read.is_set():
            low_read.set()
            assert high_done.wait(15)
        return result

    def run(stamp, value, name):
        close_old_connections()
        try:
            return ingest_nem12_content(revision(value, stamp), name)
        finally:
            close_old_connections()

    def low():
        return run("20260305000000", "0.6", "low")

    def high():
        try:
            assert low_read.wait(10)
            return run("20260306000000", "0.8", "high")
        finally:
            high_done.set()

    with (
        patch.object(ingestion, "select_current", select),
        ThreadPoolExecutor(max_workers=2) as pool,
    ):
        a, b = pool.submit(low), pool.submit(high)
        a.result(timeout=30)
        b.result(timeout=30)
    values = set(
        CurrentInterval.objects.filter(channel=channel("E1")).values_list("value", flat=True)
    )
    assert values == {Decimal("0.8")}


@pytest.mark.django_db
def test_quarantined_interval_blocks_coverage(seeded):
    ingest_nem12_content(load("day1_rev2.nem12"), "day1_rev2.nem12")
    ingest_nem12_content(load("day1_conflict.nem12"), "day1_conflict.nem12")
    cov = channel_coverage(channel("E1"), date(2026, 3, 2), date(2026, 3, 3))
    assert cov.quarantined == 1
    assert not cov.complete


def _block(minutes: int = 30, day: str = "20260302") -> str:
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


def _content(*blocks: str, sender: str = "TARYX") -> bytes:
    return (
        "100,NEM12,20260306120000," + sender + ",TARYX\n" + "\n".join(blocks) + "\n900\n"
    ).encode()


@pytest.mark.django_db
def test_mixed_interval_metadata_rejected_atomically(seeded):
    """A 5-minute block followed by a 30-minute block on one channel must
    not publish the earlier days under the later block's metadata."""
    result = ingest_nem12_content(_content(_block(5), _block(30, "20260303")), "mixed")
    assert result.batch.status == "rejected"
    assert result.batch.error_code == "conflicting_200"
    assert not IntervalRecord.objects.exists()
    assert not CurrentInterval.objects.exists()


@pytest.mark.django_db
def test_repeated_channel_day_is_explicit_rejection(seeded):
    """The same channel/day twice in one file is an inspectable rejection,
    not a database constraint escape."""
    result = ingest_nem12_content(_content(_block(), _block()), "repeated-day")
    assert result.batch.status == "rejected"
    assert result.batch.error_code == "repeated_interval"
    assert not IntervalRecord.objects.exists()


@pytest.mark.django_db
def test_identical_revision_in_new_envelope_is_selection_noop(seeded):
    """An equivalent record in a new batch envelope must not repoint the
    selection or bump selection_version — repeated revisions are no-ops."""
    ingest_nem12_content(_content(_block()), "first")
    before = list(
        CurrentInterval.objects.order_by("interval_end_utc").values_list(
            "source_record_id", "selection_version"
        )
    )
    ingest_nem12_content(_content(_block(), sender="OTHER"), "same-revision")
    after = list(
        CurrentInterval.objects.order_by("interval_end_utc").values_list(
            "source_record_id", "selection_version"
        )
    )
    assert before == after


@pytest.mark.django_db
def test_consistent_repeated_blocks_on_distinct_days_publish(seeded):
    """Repeated 200 blocks with identical metadata are legitimate
    continuations — rejection only bites on conflicting metadata or
    repeated days."""
    result = ingest_nem12_content(_content(_block(), _block(day="20260303")), "two-days")
    assert result.batch.status == "published"
    assert result.batch.record_count == 96
    assert CurrentInterval.objects.count() == 96
