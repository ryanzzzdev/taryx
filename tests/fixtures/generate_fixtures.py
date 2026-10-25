"""Deterministic NEM12 fixture generator.

Writes small .nem12 files plus expected.json (independent expected results,
hand-derived from the frozen profile — never produced by the engine).
Run: uv run python tests/fixtures/generate_fixtures.py
"""

import json
from pathlib import Path

OUT = Path(__file__).resolve().parent / "nem12"
NMI = "4102000001"
TS0 = "20260301120000"  # base UpdateDateTime / MSATSLoadDateTime
TS1 = "20260303120000"
TS2 = "20260304120000"
TS3 = "20260305120000"


def fmt(values: list[str]) -> str:
    return ",".join(values)


def day_300(day: str, values: list[str], quality: str, ts: str, reason: str = "") -> str:
    return f"300,{day},{fmt(values)},{quality},{reason},,{ts},{ts}"


def nem12(channel_lines: list[str], nmi: str = NMI, config: str = "E1B1") -> str:
    lines = [
        "100,NEM12,20260306120000,TARYX,TARYX",
        f"200,{nmi},{config},,E1,NEM100,1000001,kWh,30,",
        *channel_lines,
        "900",
    ]
    return "\n".join(lines) + "\n"


def nem12_two_channels(e1_lines: list[str], b1_lines: list[str]) -> str:
    lines = [
        "100,NEM12,20260306120000,TARYX,TARYX",
        f"200,{NMI},E1B1,,E1,NEM100,1000001,kWh,30,",
        *e1_lines,
        f"200,{NMI},E1B1,,B1,NEM100,1000001,kWh,30,",
        *b1_lines,
        "900",
    ]
    return "\n".join(lines) + "\n"


def v_day(day: str, values: list[str], quals: list[str], ts: str) -> list[str]:
    lines = [day_300(day, values, "V", ts)]
    for i, q in enumerate(quals, start=1):
        lines.append(f"400,{i},{q},,,{ts},{ts}")
    return lines


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    flat_e1 = ["0.5"] * 48
    flat_b1 = ["0.2"] * 48
    files: dict[str, str] = {}

    # RC-01/03: base day, E1 0.5 A, B1 0.2 A on 2026-03-02.
    files["day1_base.nem12"] = nem12_two_channels(
        [day_300("20260302", flat_e1, "A", TS0)],
        [day_300("20260302", flat_b1, "A", TS0)],
    )

    # RC-07a: 2026-03-03 E-quality file, then later-arriving A file.
    files["day2_est.nem12"] = nem12_two_channels(
        [day_300("20260303", ["0.4"] * 48, "E", TS1)],
        [day_300("20260303", ["0.15"] * 48, "E", TS1)],
    )
    files["day2_act.nem12"] = nem12_two_channels(
        [day_300("20260303", flat_e1, "A", TS2)],
        [day_300("20260303", flat_b1, "A", TS2)],
    )

    # RC-09: successive revisions of interval 20 (ends 10:00) on 2026-03-02.
    rev1 = flat_e1.copy()
    rev1[19] = "0.8"
    files["day1_rev1.nem12"] = nem12([day_300("20260302", rev1, "A", TS1)])
    rev2 = flat_e1.copy()
    rev2[19] = "0.6"
    files["day1_rev2.nem12"] = nem12([day_300("20260302", rev2, "A", TS2)])

    # RC-07c: same precedence keys (A + same timestamps as rev2), different value.
    conflict = flat_e1.copy()
    conflict[19] = "0.7"
    files["day1_conflict.nem12"] = nem12([day_300("20260302", conflict, "A", TS2)], config="E1B1")

    # RC-07b: substituted then final substitution on 2026-03-04.
    files["day3_sub.nem12"] = nem12([day_300("20260304", ["0.6"] * 48, "S", TS1)])
    files["day3_final.nem12"] = nem12([day_300("20260304", ["0.55"] * 48, "F", TS2)])

    # 'V' quality method with per-interval 400 records (mixed A/S/E/F day).
    quals = ["A"] * 12 + ["S"] * 12 + ["E"] * 12 + ["F"] * 12
    files["day5_var.nem12"] = nem12(v_day("20260305", flat_e1, quals, TS1))

    # Invalid inputs (RC-08).
    bad_uom = nem12([day_300("20260302", flat_e1, "A", TS0)]).replace("kWh", "MWh")
    files["bad_uom.nem12"] = bad_uom
    files["bad_interval.nem12"] = nem12([day_300("20260302", flat_e1, "A", TS0)]).replace(
        "kWh,30,", "kWh,15,"
    )
    files["nem13.nem12"] = nem12([day_300("20260302", flat_e1, "A", TS0)]).replace(
        "NEM12", "NEM13", 1
    )
    files["unknown_nmi.nem12"] = nem12([day_300("20260302", flat_e1, "A", TS0)], nmi="9999999999")
    files["out_of_order.nem12"] = nem12(
        [
            day_300("20260303", flat_e1, "A", TS0),
            day_300("20260302", flat_e1, "A", TS0),
        ]
    )
    files["v_missing_400.nem12"] = nem12([day_300("20260302", flat_e1, "V", TS0)])

    for name, text in files.items():
        (OUT / name).write_text(text, encoding="utf-8")

    expected = {
        "day1_base": {
            "status": "published",
            "records": 96,
            "e1": {"count": 48, "value": "0.500000", "quality": "A"},
            "b1": {"count": 48, "value": "0.200000", "quality": "A"},
        },
        "day2_est_then_act": {
            "e1_value": "0.500000",
            "e1_quality": "A",
            "note": "A outranks E regardless of arrival order",
        },
        "day1_revisions": {
            "after_rev1_interval20": "0.800000",
            "after_rev2_interval20": "0.600000",
            "flat_intervals": "0.500000",
        },
        "day1_conflict": {
            "open_quarantines": 1,
            "current_value_unchanged": "0.600000",
        },
        "day3_sub_then_final": {"e1_value": "0.550000", "e1_quality": "F"},
        "day5_var": {
            "status": "published",
            "qualities": {"A": 12, "S": 12, "E": 12, "F": 12},
        },
        "rejections": {
            "bad_uom": "unsupported_uom",
            "bad_interval": "unsupported_interval",
            "nem13": "unsupported_version",
            "unknown_nmi": "unknown_nmi",
            "out_of_order": "out_of_order",
            "v_missing_400": "missing_400",
        },
    }
    (OUT / "expected.json").write_text(json.dumps(expected, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(files)} files + expected.json to {OUT}")


if __name__ == "__main__":
    main()
