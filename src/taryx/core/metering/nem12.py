"""NEM12 (MDFF interval data) parser for the frozen supported subset.

Pure parsing: returns structured records, performs format-level validation
and raises Nem12Error with a stable error code on the first defect.

Format rules implemented (AEMO MDFF Specification v2.7, sections 3.3 and 4):

- QualityMethod is `QMM`: a one-letter quality flag optionally followed by a
  two-digit substitution/estimation method code (e.g. ``E52``, ``S14``).
  ``A`` carries no method; ``V`` is only valid on a 300 record.
- ReasonCode is mandatory for ``S`` and ``F`` flags, optional otherwise.
- IntervalValues are plain non-negative decimals (up to 9 integer and
  6 fractional digits). Signs, exponents and non-finite values are rejected.
- 400 records are ``400,StartInterval,EndInterval,QualityMethod,ReasonCode,
  ReasonDescription`` and apply to the immediately preceding 300 record.
  Their ranges must tile the entire day ascending, without gaps or overlaps.
  The 400 QualityMethod/ReasonCode applies to every interval in the range;
  interval timestamps are inherited from the parent 300 record.
"""

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from taryx.core.metering.nem_time import NEM_TZ, nem_intervals_per_day

SUPPORTED_INTERVAL_MINUTES = {5, 30}
SUPPORTED_UOM = {"kwh"}
QUALITY_FLAGS = {"A", "S", "E", "F"}

_QUALITY_METHOD_RE = re.compile(r"^([SEF])(\d{2})?$")
_INTERVAL_VALUE_RE = re.compile(r"^\d{1,9}(\.\d{1,6})?$")
_REASON_CODE_RE = re.compile(r"^\d{1,3}$")


class Nem12Error(ValueError):
    def __init__(self, code: str, detail: str):
        self.code = code
        super().__init__(detail)


@dataclass
class IntervalValue:
    interval_number: int
    value: Decimal
    quality: str | None
    method_code: str | None
    reason_code: str | None
    update_dt: datetime | None
    msats_load_dt: datetime | None


@dataclass
class IntervalDay:
    interval_date: date
    values: list[IntervalValue]
    row_number: int
    day_quality: str
    update_dt: datetime | None
    msats_load_dt: datetime | None


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


def _parse_quality_method(raw: str, *, allow_v: bool, row_number: int) -> tuple[str, str | None]:
    qm = raw.strip().upper()
    if allow_v and qm == "V":
        return "V", None
    if qm == "A":
        return "A", None
    match = _QUALITY_METHOD_RE.fullmatch(qm)
    if match is None:
        raise Nem12Error("bad_quality", f"row {row_number}: QualityMethod {qm!r}")
    return match.group(1), match.group(2)


def _check_reason(flag: str, reason: str | None, row_number: int, context: str) -> None:
    if reason is not None and not _REASON_CODE_RE.fullmatch(reason):
        raise Nem12Error("bad_reason", f"row {row_number}: ReasonCode {reason!r} on {context}")
    if flag in {"S", "F"} and reason is None:
        raise Nem12Error(
            "missing_reason",
            f"row {row_number}: ReasonCode required for flag {flag!r} on {context}",
        )


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
    seen_days: dict[tuple[str, str], set[date]] = {}
    channels: list[ChannelData] = []
    current: ChannelData | None = None
    current_meta: ChannelMeta | None = None
    last_date: date | None = None
    expected_per_day = 0
    pending_day: IntervalDay | None = None
    covered_until = 0

    def finalize_pending() -> None:
        nonlocal pending_day, covered_until
        if pending_day is not None:
            n = len(pending_day.values)
            if pending_day.day_quality == "V" and covered_until == 0:
                raise Nem12Error(
                    "missing_400",
                    f"row {pending_day.row_number}: 'V' day lacks 400 records",
                )
            if covered_until and covered_until != n:
                raise Nem12Error(
                    "incomplete_400",
                    f"row {pending_day.row_number}: 400 ranges cover "
                    f"{covered_until} of {n} intervals",
                )
        pending_day = None
        covered_until = 0

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
            if not nmi:
                raise Nem12Error("malformed_200", f"row {row_number}: empty NMI")
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
            previous = meta.get((nmi, suffix))
            if previous is not None and previous != current_meta:
                # A repeated channel block must declare identical metadata:
                # earlier days were parsed under their own block's interval
                # length, so letting the last block's metadata stand would
                # re-time every interval already collected.
                raise Nem12Error(
                    "conflicting_200",
                    f"row {row_number}: repeated 200 for {nmi}:{suffix} changes channel metadata",
                )
            meta[(nmi, suffix)] = current_meta
            current = ChannelData(nmi=nmi, suffix=suffix)
            channels.append(current)
            last_date = None
            expected_per_day = nem_intervals_per_day(interval_minutes)

        elif kind == "300":
            if current_meta is None or current is None:
                raise Nem12Error("orphan_300", f"row {row_number}: 300 before any 200")
            if len(row) < 7:
                raise Nem12Error("malformed_300", f"row {row_number}: 300 record too short")
            try:
                interval_date = datetime.strptime(row[1].strip(), "%Y%m%d").date()
            except ValueError:
                raise Nem12Error("invalid_date", f"row {row_number}: bad IntervalDate") from None
            if last_date is not None and interval_date <= last_date:
                raise Nem12Error("out_of_order", f"row {row_number}: IntervalDate not ascending")
            last_date = interval_date
            channel_days = seen_days.setdefault((current.nmi, current.suffix), set())
            if interval_date in channel_days:
                # The same channel/day twice in one file is a duplicate
                # interval identity — an explicit defect, not a constraint
                # violation left for the database to find.
                raise Nem12Error(
                    "repeated_interval",
                    f"row {row_number}: repeated interval day {interval_date} "
                    f"for {current.nmi}:{current.suffix}",
                )
            channel_days.add(interval_date)
            n_values = len(row) - 7
            if n_values != expected_per_day:
                raise Nem12Error(
                    "bad_interval_count",
                    f"row {row_number}: {n_values} values, expected {expected_per_day}",
                )
            day_quality, day_method = _parse_quality_method(
                row[2 + n_values], allow_v=True, row_number=row_number
            )
            reason_code = row[3 + n_values].strip() or None
            _check_reason(day_quality, reason_code, row_number, "300")
            update_dt = _parse_dt(row[5 + n_values])
            msats_load_dt = _parse_dt(row[6 + n_values])
            values: list[IntervalValue] = []
            day = IntervalDay(
                interval_date, values, row_number, day_quality, update_dt, msats_load_dt
            )
            for idx, raw_value in enumerate(row[2 : 2 + n_values], start=1):
                token = raw_value.strip()
                if not _INTERVAL_VALUE_RE.fullmatch(token):
                    raise Nem12Error(
                        "bad_value",
                        f"row {row_number}: interval value {token!r} is not a "
                        "supported non-negative decimal",
                    )
                value = Decimal(token)
                if day_quality == "V":
                    values.append(IntervalValue(idx, value, None, None, None, None, None))
                else:
                    values.append(
                        IntervalValue(
                            idx,
                            value,
                            day_quality,
                            day_method,
                            reason_code,
                            update_dt,
                            msats_load_dt,
                        )
                    )
            current.days.append(day)
            pending_day = day

        elif kind == "400":
            if pending_day is None:
                raise Nem12Error("orphan_400", f"row {row_number}: 400 without a preceding 300")
            if len(row) != 6:
                raise Nem12Error(
                    "malformed_400",
                    f"row {row_number}: 400 record has {len(row) - 1} fields, expected 5",
                )
            try:
                start = int(row[1].strip())
                end = int(row[2].strip())
            except ValueError:
                raise Nem12Error("malformed_400", f"row {row_number}: bad interval range") from None
            n = len(pending_day.values)
            if not (1 <= start <= end <= n) or start != covered_until + 1:
                raise Nem12Error(
                    "bad_400_range",
                    f"row {row_number}: range {start}-{end} invalid or "
                    f"overlapping (expected start {covered_until + 1} of {n})",
                )
            flag, method = _parse_quality_method(row[3], allow_v=False, row_number=row_number)
            reason_code = row[4].strip() or None
            _check_reason(flag, reason_code, row_number, "400")
            for idx in range(start, end + 1):
                target = pending_day.values[idx - 1]
                target.quality = flag
                target.method_code = method
                target.reason_code = reason_code
                target.update_dt = pending_day.update_dt
                target.msats_load_dt = pending_day.msats_load_dt
            covered_until = end

        elif kind == "500":
            continue

        else:
            raise Nem12Error("unknown_record", f"row {row_number}: record {kind!r}")

    finalize_pending()
    if not channels:
        raise Nem12Error("no_data", "no 200/300 records in file")
    return meta, channels
