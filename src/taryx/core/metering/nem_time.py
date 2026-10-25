from datetime import UTC, date, datetime, timedelta, timezone

NEM_TZ = timezone(timedelta(hours=10), name="NEM")


def nem_interval_end_utc(
    interval_date: date, interval_number: int, interval_minutes: int
) -> datetime:
    """UTC instant of the end of NEM interval `interval_number` on `interval_date`.

    Interval n covers (00:00 + (n-1)L, 00:00 + nL] in NEM time (fixed UTC+10).
    """
    end_nem = datetime.combine(interval_date, datetime.min.time(), tzinfo=NEM_TZ) + timedelta(
        minutes=interval_number * interval_minutes
    )
    return end_nem.astimezone(UTC)


def nem_intervals_per_day(interval_minutes: int) -> int:
    return (24 * 60) // interval_minutes
