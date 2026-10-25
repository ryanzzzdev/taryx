"""NEM12 (MDFF interval data) parser for the frozen supported subset.

Pure parsing: returns structured records, performs format-level validation
and raises Nem12Error with a stable error code on the first defect.
"""

import csv
import io
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from taryx.core.metering.nem_time import NEM_TZ, nem_intervals_per_day

SUPPORTED_INTERVAL_MINUTES = {5, 30}
SUPPORTED_UOM = {"kwh"}
QUALITY_FLAGS = {"A", "S", "E", "F"}


class Nem12Error(ValueError):
    def __init__(self, code: str, detail: str):
        self.code = code
        super().__init__(detail)


@dataclass
class IntervalValue:
    interval_number: int
    value: Decimal
    quality: str | None
    reason_code: str | None
    update_dt: datetime | None
    msats_load_dt: datetime | None


@dataclass
class IntervalDay:
    interval_date: date
    values: list[IntervalValue]
    row_number: int


@dataclass
class ChannelData:
    nmi: str
    suffix: str
    days: list[IntervalDay] = field(default_factory=list)


@dataclass(frozen=True)
class ChannelMeta:
    nmi: str
    configuration: str
    suffix: str
    uom: str
    interval_minutes: int


def _parse_dt(raw: str) -> datetime | None:
    raw = raw.strip()
    if not raw:
        return None
    for fmt in ("%Y%m%d%H%M%S", "%Y%m%d%H%M"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=NEM_TZ)
        except ValueError:
            pass
    raise Nem12Error("invalid_datetime", f"cannot parse datetime {raw!r}")


def parse_nem12(text: str) -> tuple[dict[tuple[str, str], ChannelMeta], list[ChannelData]]:
    """Parse NEM12 text into channel metadata and interval days.

    Returns ({(nmi, suffix): ChannelMeta}, [ChannelData in file order]).
    """
    reader = csv.reader(io.StringIO(text.strip()))
    rows = [r for r in reader if r and r[0].strip()]
    if len(rows) < 3:
        raise Nem12Error("empty_file", "file too short to contain a NEM12 block")

    header = rows[0]
    if header[0] != "100":
        raise Nem12Error("missing_header", "first record is not a 100 header")
    if len(header) < 2 or header[1].strip() != "NEM12":
        raise Nem12Error("unsupported_version", "VersionHeader is not 'NEM12'")
    if rows[-1][0] != "900":
        raise Nem12Error("missing_end", "last record is not a 900 end record")
    for i, row in enumerate(rows):
        if row[0] == "100" and i != 0:
            raise Nem12Error("multiple_headers", "multiple 100 records found")

    meta: dict[tuple[str, str], ChannelMeta] = {}
    channels: list[ChannelData] = []
    current: ChannelData | None = None
    current_meta: ChannelMeta | None = None
    last_date: date | None = None
    expected_per_day = 0
    pending_day: IntervalDay | None = None
    pending_uncovered: set[int] = set()

    def finalize_pending() -> None:
        nonlocal pending_day
        if pending_day is not None and pending_uncovered:
            raise Nem12Error(
                "missing_400",
                f"row {pending_day.row_number}: 'V' intervals "
                f"{sorted(pending_uncovered)} lack 400 records",
            )
        pending_day = None

    for row_number, row in enumerate(rows[1:-1], start=2):
        kind = row[0]

        if kind != "400":
            finalize_pending()

        if kind == "200":
            if len(row) < 9:
                raise Nem12Error("malformed_200", f"row {row_number}: 200 record too short")
            nmi = row[1].strip()
            suffix = row[4].strip()
            uom = row[7].strip()
            try:
                interval_minutes = int(row[8].strip())
            except ValueError:
                raise Nem12Error("malformed_200", f"row {row_number}: bad IntervalLength") from None
            if uom.lower() not in SUPPORTED_UOM:
                raise Nem12Error("unsupported_uom", f"row {row_number}: UOM {uom!r}")
            if interval_minutes not in SUPPORTED_INTERVAL_MINUTES:
                raise Nem12Error(
                    "unsupported_interval",
                    f"row {row_number}: IntervalLength {interval_minutes}",
                )
            if not (suffix.upper().startswith("E") or suffix.upper() == "B1"):
                raise Nem12Error("unsupported_suffix", f"row {row_number}: suffix {suffix!r}")
            current_meta = ChannelMeta(
                nmi=nmi,
                configuration=row[2].strip(),
                suffix=suffix,
                uom=uom,
                interval_minutes=interval_minutes,
            )
            meta[(nmi, suffix)] = current_meta
            current = ChannelData(nmi=nmi, suffix=suffix)
            channels.append(current)
            last_date = None
            expected_per_day = nem_intervals_per_day(interval_minutes)

        elif kind == "300":
            if current_meta is None or current is None:
                raise Nem12Error("orphan_300", f"row {row_number}: 300 before any 200")
            try:
                interval_date = datetime.strptime(row[1].strip(), "%Y%m%d").date()
            except ValueError:
                raise Nem12Error("invalid_date", f"row {row_number}: bad IntervalDate") from None
            if last_date is not None and interval_date <= last_date:
                raise Nem12Error("out_of_order", f"row {row_number}: IntervalDate not ascending")
            last_date = interval_date
            n_values = len(row) - 7
            if n_values != expected_per_day:
                raise Nem12Error(
                    "bad_interval_count",
                    f"row {row_number}: {n_values} values, expected {expected_per_day}",
                )
            day_quality = row[2 + n_values].strip().upper()
            reason_code = row[3 + n_values].strip() or None
            update_dt = _parse_dt(row[5 + n_values])
            msats_load_dt = _parse_dt(row[6 + n_values])
            if day_quality != "V" and day_quality not in QUALITY_FLAGS:
                raise Nem12Error("bad_quality", f"row {row_number}: quality {day_quality!r}")
            values: list[IntervalValue] = []
            day = IntervalDay(interval_date, values, row_number)
            for idx, raw_value in enumerate(row[2 : 2 + n_values], start=1):
                try:
                    value = Decimal(raw_value.strip())
                except InvalidOperation:
                    raise Nem12Error(
                        "bad_value", f"row {row_number}: non-numeric interval value"
                    ) from None
                if day_quality == "V":
                    values.append(IntervalValue(idx, value, None, None, None, None))
                    pending_uncovered.add(idx)
                else:
                    values.append(
                        IntervalValue(
                            idx, value, day_quality, reason_code, update_dt, msats_load_dt
                        )
                    )
            current.days.append(day)
            if day_quality == "V":
                pending_day = day

        elif kind == "400":
            if pending_day is None:
                raise Nem12Error("orphan_400", f"row {row_number}: 400 without a pending 'V' day")
            if len(row) < 7:
                raise Nem12Error("malformed_400", f"row {row_number}: 400 record too short")
            try:
                interval_number = int(row[1].strip())
            except ValueError:
                raise Nem12Error("malformed_400", f"row {row_number}: bad IntervalNumber") from None
            quality = row[2].strip().upper()
            if quality not in QUALITY_FLAGS:
                raise Nem12Error("bad_quality", f"row {row_number}: 400 quality {quality!r}")
            if not (1 <= interval_number <= len(pending_day.values)):
                raise Nem12Error(
                    "bad_400_interval",
                    f"row {row_number}: interval {interval_number} out of range",
                )
            target = pending_day.values[interval_number - 1]
            target.quality = quality
            target.reason_code = row[3].strip() or None
            target.update_dt = _parse_dt(row[5]) if len(row) > 5 else None
            target.msats_load_dt = _parse_dt(row[6]) if len(row) > 6 else None
            pending_uncovered.discard(interval_number)

        elif kind == "500":
            continue

        else:
            raise Nem12Error("unknown_record", f"row {row_number}: record {kind!r}")

    finalize_pending()
    if not channels:
        raise Nem12Error("no_data", "no 200/300 records in file")
    return meta, channels
