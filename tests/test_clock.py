"""
Regression tests for UTC -> IST conversion. Timezone math must always
happen in code (src/clock.py), never be left to the LLM — a real bug had
the composer relabel a raw UTC timestamp "(IST)" without converting it.
"""
from src.clock import format_ist, parse_utc, to_ist


def test_b1164_booked_at_utc_to_ist_crosses_midnight():
    """B-1164 is booked at 2026-06-30 19:33:00 UTC, which is the whole
    reason it's a v2 (not v1) booking despite its UTC date reading 30 Jun:
    in IST it's already past midnight on 1 July."""
    dt = parse_utc("2026-06-30 19:33:00")
    ist = to_ist(dt)
    assert ist.strftime("%Y-%m-%d %H:%M:%S") == "2026-07-01 01:03:00"
    assert format_ist(dt, with_seconds=True) == "2026-07-01 01:03:00 IST"


def test_b1165_booked_at_utc_to_ist_also_crosses_midnight():
    dt = parse_utc("2026-06-30 20:15:00")
    ist = to_ist(dt)
    assert ist.strftime("%Y-%m-%d %H:%M:%S") == "2026-07-01 01:45:00"


def test_date_boundary_just_before_midnight_ist_rollover():
    """18:29:59 UTC is still 30 June in IST (one second before the v2
    cutoff); 18:30:00 UTC is already 1 July 00:00:00 IST exactly."""
    before = parse_utc("2026-06-30 18:29:59")
    at_cutoff = parse_utc("2026-06-30 18:30:00")
    assert to_ist(before).strftime("%Y-%m-%d %H:%M:%S") == "2026-06-30 23:59:59"
    assert to_ist(at_cutoff).strftime("%Y-%m-%d %H:%M:%S") == "2026-07-01 00:00:00"


def test_date_boundary_no_rollover_case():
    """A time early enough in the UTC day that +5:30 doesn't cross midnight."""
    dt = parse_utc("2026-03-15 10:00:00")
    assert to_ist(dt).strftime("%Y-%m-%d %H:%M:%S") == "2026-03-15 15:30:00"


def test_b0001_scheduled_start_conversion():
    """Cross-checks the exact value shown in the Streamlit UI during manual
    testing: 2026-08-15 04:30:00 UTC -> 2026-08-15 10:00 IST (no rollover)."""
    dt = parse_utc("2026-08-15 04:30:00")
    assert format_ist(dt) == "2026-08-15 10:00 IST"


def test_format_ist_without_seconds_by_default():
    dt = parse_utc("2026-01-01 00:00:00")
    assert format_ist(dt) == "2026-01-01 05:30 IST"
    assert format_ist(dt, with_seconds=True) == "2026-01-01 05:30:00 IST"
