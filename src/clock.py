"""
Time utilities. All stored timestamps are UTC text 'YYYY-MM-DD HH:MM:SS'.
Customers are in Bengaluru -> display times in IST (UTC+5:30) and say so.

Never do date arithmetic with julianday() floats (exact 2h can show as
1.9999h in SQLite). Always compare/subtract using integer seconds via
datetime, in Python.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from src.rules_config import IST_OFFSET_HOURS, IST_OFFSET_MINUTES

UTC_FMT = "%Y-%m-%d %H:%M:%S"
IST_DELTA = timedelta(hours=IST_OFFSET_HOURS, minutes=IST_OFFSET_MINUTES)


def parse_utc(ts: str) -> datetime:
    """Parse a stored UTC timestamp string into a naive UTC datetime."""
    return datetime.strptime(ts, UTC_FMT)


def now_utc() -> datetime:
    """Real clock 'now' in UTC, overridable via NOW_OVERRIDE for tests.

    NOW_OVERRIDE accepts 'YYYY-MM-DD HH:MM:SS' (UTC) for consistency with
    stored timestamps.
    """
    override = os.environ.get("NOW_OVERRIDE")
    if override:
        return parse_utc(override)
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_ist(dt: datetime) -> datetime:
    """Convert a naive UTC datetime to a naive IST (UTC+5:30) datetime."""
    return dt + IST_DELTA


def format_ist(dt: datetime, with_seconds: bool = False) -> str:
    ist = to_ist(dt)
    fmt = "%Y-%m-%d %H:%M:%S IST" if with_seconds else "%Y-%m-%d %H:%M IST"
    return ist.strftime(fmt)


def seconds_between(earlier: datetime, later: datetime) -> int:
    """Whole seconds from earlier to later (can be negative). Never float."""
    return int((later - earlier).total_seconds())


def hours_between_exact(earlier: datetime, later: datetime) -> Decimal:
    """Exact hours (as Decimal) between two datetimes, from integer seconds."""
    secs = seconds_between(earlier, later)
    return Decimal(secs) / Decimal(3600)


def previous_calendar_month_ist(reference_utc: datetime) -> tuple[datetime, datetime]:
    """Return (start, end) of the previous calendar month in IST, as naive IST datetimes.

    'Last month' means the previous calendar month in IST (per the brief).
    End is exclusive (start of the reference month).
    """
    ref_ist = to_ist(reference_utc)
    first_of_this_month = ref_ist.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    last_of_prev_month = first_of_this_month - timedelta(seconds=1)
    first_of_prev_month = last_of_prev_month.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return first_of_prev_month, first_of_this_month
