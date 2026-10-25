"""Deterministic current-interval selection per the frozen profile.

Precedence: quality A > F > S > E, then MSATSLoadDateTime, then
UpdateDateTime. Records tying on all three but differing in value are a
conflict (quarantine); identical values resolve deterministically by
batch/row recency so repeated revisions are no-ops.
"""

from datetime import UTC, datetime

from taryx.core.metering.models import IntervalRecord

QUALITY_RANK = {"A": 4, "F": 3, "S": 2, "E": 1}
_MIN_DT = datetime.min.replace(tzinfo=UTC)


def precedence(record: IntervalRecord) -> tuple:
    return (
        QUALITY_RANK.get(record.quality, 0),
        record.msats_load_dt or _MIN_DT,
        record.update_dt or _MIN_DT,
    )


def _order(record: IntervalRecord) -> tuple:
    return precedence(record) + (record.batch_id, record.row_number)


def select_current(records: list[IntervalRecord]) -> tuple[IntervalRecord | None, bool]:
    """Return (winner, is_conflict) for candidate records of one interval."""
    if not records:
        return None, False
    best_precedence = max(precedence(r) for r in records)
    top = [r for r in records if precedence(r) == best_precedence]
    if len({r.value for r in top}) > 1:
        return None, True
    return max(top, key=_order), False
