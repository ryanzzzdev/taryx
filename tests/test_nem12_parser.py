"""Pure-parser regressions for the corrected NEM12 profile (M1 review R1/R4)."""

from pathlib import Path

import pytest

from taryx.core.metering.nem12 import Nem12Error, parse_nem12

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "nem12"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text()


def edit_300(text: str, func) -> str:
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("300,"):
            row = line.split(",")
            func(row)
            lines[i] = ",".join(row)
    return "\n".join(lines) + "\n"


def test_300_quality_method_with_method_code():
    meta, channels = parse_nem12(fixture("day2_est.nem12"))
    day = channels[0].days[0]  # day2_est declares QualityMethod E52
    assert day.day_quality == "E"
    assert {v.quality for v in day.values} == {"E"}
    assert {v.method_code for v in day.values} == {"52"}


def test_ranged_400_records_tile_day():
    text = fixture("day5_var.nem12")
    rows = [r for r in text.splitlines() if not r.startswith("400,")]
    rows.insert(-1, "400,1,24,A,,")
    rows.insert(-1, "400,25,48,E52,,")
    _, channels = parse_nem12("\n".join(rows))
    values = channels[0].days[0].values
    assert {v.quality for v in values[:24]} == {"A"}
    assert {v.quality for v in values[24:]} == {"E"}
    assert {v.method_code for v in values[24:]} == {"52"}


def test_400_inherits_300_timestamps():
    _, channels = parse_nem12(fixture("day5_var.nem12"))
    day = channels[0].days[0]
    assert {v.update_dt for v in day.values} == {day.update_dt}
    assert {v.msats_load_dt for v in day.values} == {day.msats_load_dt}


@pytest.mark.parametrize("value", ["-0.5", "+0.5", "NaN", "Infinity", "1e2", "1E-2", ".5", "0.5e0"])
def test_interval_value_lexical_form_rejected(value):
    text = edit_300(fixture("day1_base.nem12"), lambda r: r.__setitem__(2, value))
    with pytest.raises(Nem12Error) as exc:
        parse_nem12(text)
    assert exc.value.code == "bad_value"


def test_truncated_300_raises_stable_error():
    rows = fixture("day1_base.nem12").splitlines()
    rows[2] = "300"
    with pytest.raises(Nem12Error) as exc:
        parse_nem12("\n".join(rows))
    assert exc.value.code == "malformed_300"


@pytest.mark.parametrize(
    "record,code",
    [
        ("400,1,10", "malformed_400"),
        ("400,1,48,A,,,extra", "malformed_400"),
        ("400,1,30,A,,", None),  # combined with following lines below
        ("400,30,10,A,,", "bad_400_range"),
        ("400,0,10,A,,", "bad_400_range"),
        ("400,1,49,A,,", "bad_400_range"),
        ("400,1,48,V,,", "bad_quality"),
        ("400,1,48,S14,,", "missing_reason"),
    ],
)
def test_malformed_400_records(record, code):
    text = fixture("v_missing_400.nem12").replace("900", f"{record}\n900")
    if code is None:
        # Partial tiling without a complementary range: incomplete coverage.
        with pytest.raises(Nem12Error) as exc:
            parse_nem12(text)
        assert exc.value.code == "incomplete_400"
        return
    with pytest.raises(Nem12Error) as exc:
        parse_nem12(text)
    assert exc.value.code == code


def test_overlapping_400_ranges_rejected():
    text = fixture("v_missing_400.nem12").replace("900", "400,1,30,A,,\n400,25,48,A,,\n900")
    with pytest.raises(Nem12Error) as exc:
        parse_nem12(text)
    assert exc.value.code == "bad_400_range"


def test_sf_without_reason_rejected():
    text = edit_300(fixture("day3_sub.nem12"), lambda r: r.__setitem__(3 + 48, ""))
    with pytest.raises(Nem12Error) as exc:
        parse_nem12(text)
    assert exc.value.code == "missing_reason"
