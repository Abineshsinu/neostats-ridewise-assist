"""
Vetted, parameterised tools. These are tried before any fallback
LLM-written SQL. Every tool takes an already-scoped connection (a
customer sandbox or the agent masked connection) and returns a
(result, evidence) pair — evidence always carries the row ids used and,
for anything money/time related, the calculator's step-by-step working.

Ownership is structural, not trusted: a customer's connection physically
contains only their own rows (see src/sandbox.py), so looking up a
booking_id that belongs to someone else returns exactly the same "not
found" result as a booking_id that doesn't exist anywhere. The caller
(the orchestrator, not the LLM) must always resolve booking_id against
the session's own connection before use — never trust a planner-extracted
id without this lookup.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal

from src import calculators as calc
from src.clock import format_ist, hours_between_exact, now_utc, parse_utc

NOT_FOUND_MESSAGE = (
    "I couldn't find a booking with that ID on this account. "
    "Please check the booking ID and try again."
)


def _ist(utc_str: str | None) -> str | None:
    """Convert a stored UTC timestamp string to a formatted IST string in
    code — never leave timezone arithmetic to the LLM, which will happily
    relabel a raw UTC value "(IST)" without actually converting it."""
    if not utc_str:
        return None
    return format_ist(parse_utc(utc_str))


def _with_ist_times(row: dict, fields: list[str]) -> dict:
    d = dict(row)
    for f in fields:
        if f in d:
            d[f"{f}_ist"] = _ist(d[f])
    return d


@dataclass
class ToolResult:
    ok: bool
    data: dict | list | None = None
    evidence: list[dict] = field(default_factory=list)
    message: str | None = None


def resolve_booking(con: sqlite3.Connection, booking_id: str) -> sqlite3.Row | None:
    """The single choke point every tool must use to look up a booking.
    Returns None for both 'does not exist' and 'belongs to someone else',
    indistinguishably, because the connection itself only contains rows
    the session is entitled to see."""
    cur = con.cursor()
    cur.execute("SELECT * FROM bookings WHERE booking_id = ?", (booking_id,))
    return cur.fetchone()


def list_my_bookings(con: sqlite3.Connection, limit: int = 50) -> ToolResult:
    cur = con.cursor()
    cur.execute(
        "SELECT booking_id, vehicle_id, booking_status, scheduled_start, scheduled_end "
        "FROM bookings ORDER BY scheduled_start DESC LIMIT ?",
        (limit,),
    )
    rows = [_with_ist_times(dict(r), ["scheduled_start", "scheduled_end"]) for r in cur.fetchall()]
    evidence = [{"type": "data", "table": "bookings", "row_ids": [r["booking_id"] for r in rows]}]
    return ToolResult(ok=True, data=rows, evidence=evidence)


def booking_detail(con: sqlite3.Connection, booking_id: str) -> ToolResult:
    row = resolve_booking(con, booking_id)
    if row is None:
        return ToolResult(ok=False, message=NOT_FOUND_MESSAGE)
    cur = con.cursor()
    cur.execute("SELECT * FROM vehicles WHERE vehicle_id = ?", (row["vehicle_id"],))
    vehicle = cur.fetchone()
    booking_data = _with_ist_times(dict(row), ["booked_at", "scheduled_start", "scheduled_end", "actual_return_at", "cancelled_at"])
    data = {"booking": booking_data, "vehicle": dict(vehicle) if vehicle else None}
    evidence = [{"type": "data", "table": "bookings", "row_ids": [booking_id]}]
    if vehicle:
        evidence.append({"type": "data", "table": "vehicles", "row_ids": [vehicle["vehicle_id"]]})
    return ToolResult(ok=True, data=data, evidence=evidence)


def payments_for_booking(con: sqlite3.Connection, booking_id: str) -> ToolResult:
    row = resolve_booking(con, booking_id)
    if row is None:
        return ToolResult(ok=False, message=NOT_FOUND_MESSAGE)
    cur = con.cursor()
    cur.execute("SELECT * FROM payments WHERE booking_id = ? ORDER BY paid_at", (booking_id,))
    payments = [_with_ist_times(dict(r), ["paid_at"]) for r in cur.fetchall()]
    evidence = [{"type": "data", "table": "payments", "row_ids": [p["payment_id"] for p in payments]}]
    return ToolResult(ok=True, data=payments, evidence=evidence)


def refund_estimate(con: sqlite3.Connection, booking_id: str) -> ToolResult:
    """Refund if cancelled now (for UPC), or the refund that applied to an
    actual cancellation (for CNL_U/CNL_S), or the applicable policy
    statement for other statuses (NSH/ONG/CMP)."""
    row = resolve_booking(con, booking_id)
    if row is None:
        return ToolResult(ok=False, message=NOT_FOUND_MESSAGE)

    cur = con.cursor()
    cur.execute(
        "SELECT COALESCE(SUM(amount),0) AS amt, COALESCE(SUM(gst_amount),0) AS gst FROM payments "
        "WHERE booking_id = ? AND payment_type = 'BOOKING' AND payment_status = 'SUCCESS'",
        (booking_id,),
    )
    paid = cur.fetchone()
    rental_paid, gst_paid = Decimal(str(paid["amt"])), Decimal(str(paid["gst"]))

    cur.execute(
        "SELECT COALESCE(SUM(amount),0) AS amt FROM payments WHERE booking_id = ? "
        "AND payment_type = 'REFUND'",
        (booking_id,),
    )
    existing_refund = cur.fetchone()["amt"]

    status = row["booking_status"]
    version_result = calc.policy_version(row["booked_at"])
    version = version_result.value

    assumptions = []
    if status == "UPC":
        hours_before = max(Decimal(0), calc_hours_before(now_utc(), row["scheduled_start"]))
        assumptions.append("Hypothetical: refund if you cancelled right now (booking is still UPC/upcoming).")
    elif status in ("CNL_U", "CNL_S"):
        ref_time = parse_utc(row["cancelled_at"]) if row["cancelled_at"] else now_utc()
        hours_before = max(Decimal(0), calc_hours_before(ref_time, row["scheduled_start"]))
    else:
        hours_before = Decimal(0)

    refund_result = calc.refund(status, version, hours_before, rental_paid, gst_paid)

    data = {
        "booking_id": booking_id,
        "booking_status": status,
        "policy_version": version,
        "rental_paid": str(rental_paid),
        "gst_paid": str(gst_paid),
        "existing_refund_recorded": existing_refund,
        "computed": {k: str(v) for k, v in refund_result.value.items()},
    }
    if existing_refund == 0 and status == "CNL_U":
        data["note"] = "Refund owed but not yet recorded in payment records (processed within 3 working days of cancellation)."

    evidence = [
        {"type": "data", "table": "bookings", "row_ids": [booking_id]},
        {"type": "calculation", "tool": "policy_version", "steps": version_result.steps, "citations": _cite(version_result)},
        {"type": "calculation", "tool": "refund", "steps": refund_result.steps, "citations": _cite(refund_result)},
    ]
    return ToolResult(ok=True, data=data, evidence=evidence, message="; ".join(assumptions) or None)


def explain_charge(con: sqlite3.Connection, booking_id: str) -> ToolResult:
    """Recompute every penalty-type charge on a booking and show the working,
    so the caller can match it against what the customer says they were charged."""
    row = resolve_booking(con, booking_id)
    if row is None:
        return ToolResult(ok=False, message=NOT_FOUND_MESSAGE)

    cur = con.cursor()
    cur.execute("SELECT * FROM vehicles WHERE vehicle_id = ?", (row["vehicle_id"],))
    vehicle = cur.fetchone()
    cur.execute("SELECT customer_id FROM bookings WHERE booking_id = ?", (booking_id,))
    customer_id = cur.fetchone()["customer_id"]
    cur.execute("SELECT customer_tier FROM customers WHERE customer_id = ?", (customer_id,))
    tier_row = cur.fetchone()
    tier = tier_row["customer_tier"] if tier_row else "STANDARD"

    cur.execute("SELECT * FROM payments WHERE booking_id = ? AND payment_type = 'PENALTY'", (booking_id,))
    penalty_rows = [dict(r) for r in cur.fetchall()]

    cur.execute("SELECT * FROM damage_reports WHERE booking_id = ?", (booking_id,))
    damage_rows = [dict(r) for r in cur.fetchall()]

    explanations = []
    evidence = [{"type": "data", "table": "bookings", "row_ids": [booking_id]}]

    if row["actual_return_at"] and vehicle:
        late_result = calc.late_fee(parse_utc(row["scheduled_end"]), parse_utc(row["actual_return_at"]), Decimal(str(vehicle["hourly_rate"])), tier)
        explanations.append({"check": "late_fee", "result": {k: str(v) for k, v in late_result.value.items()}, "steps": late_result.steps})
        evidence.append({"type": "calculation", "tool": "late_fee", "steps": late_result.steps, "citations": _cite(late_result)})

        if vehicle["vehicle_type"] in ("EV_SCOOTER", "EV_BIKE"):
            batt_result = calc.battery_fee(vehicle["vehicle_type"], row["return_battery_pct"])
            if batt_result.value is not None:
                explanations.append({"check": "battery_fee", "result": {k: str(v) for k, v in batt_result.value.items()}, "steps": batt_result.steps})
                evidence.append({"type": "calculation", "tool": "battery_fee", "steps": batt_result.steps, "citations": _cite(batt_result)})

    for dmg in damage_rows:
        dmg_result = calc.damage_chargeable(dmg["claim_status"], Decimal(str(dmg["assessed_cost"])))
        explanations.append({"check": "damage", "report_id": dmg["report_id"], "result": str(dmg_result.value), "steps": dmg_result.steps})
        evidence.append({"type": "calculation", "tool": "damage_chargeable", "steps": dmg_result.steps, "citations": _cite(dmg_result)})

    evidence.append({"type": "data", "table": "payments", "row_ids": [p["payment_id"] for p in penalty_rows]})
    if damage_rows:
        evidence.append({"type": "data", "table": "damage_reports", "row_ids": [d["report_id"] for d in damage_rows]})

    data = {
        "booking_id": booking_id,
        "recorded_penalty_payments": penalty_rows,
        "recomputed_checks": explanations,
    }
    return ToolResult(ok=True, data=data, evidence=evidence)


CLARIFY_VEHICLE_MESSAGE = (
    "Which vehicle model or type (e.g. 'Honda Activa 6G' or 'scooter') did you mean? "
    "The late fee and battery fee both depend on the specific vehicle's hourly rate."
)
CLARIFY_BATTERY_PCT_MESSAGE = "What battery percentage was the vehicle returned at?"


def _find_vehicles(con: sqlite3.Connection, vehicle_model: str | None, vehicle_type: str | None) -> list[sqlite3.Row]:
    cur = con.cursor()
    if vehicle_model:
        cur.execute("SELECT * FROM vehicles WHERE model LIKE ?", (f"%{vehicle_model}%",))
        rows = cur.fetchall()
        if rows:
            return rows
    if vehicle_type:
        cur.execute("SELECT * FROM vehicles WHERE vehicle_type = ?", (vehicle_type,))
        return cur.fetchall()
    return []


def late_fee_hypothetical(
    con: sqlite3.Connection,
    vehicle_model: str | None,
    vehicle_type: str | None,
    delay_minutes: int,
    tier: str,
) -> ToolResult:
    """A direct 'what would the late fee be' question, not tied to any real
    booking — e.g. "scooter, 35 minutes late, GOLD tier". Uses the same
    calculators.late_fee as explain_charge, with a synthetic scheduled_end
    exactly delay_minutes before a synthetic actual_return so the lateness
    comes out to exactly what was asked."""
    vehicles = _find_vehicles(con, vehicle_model, vehicle_type)
    if not vehicles:
        return ToolResult(ok=False, message=CLARIFY_VEHICLE_MESSAGE)

    sched = now_utc()
    actual = sched + timedelta(minutes=delay_minutes)

    results = []
    evidence = []
    for v in vehicles[:6]:  # cap: if a bare vehicle_type matches many models, show a representative set
        result = calc.late_fee(sched, actual, Decimal(str(v["hourly_rate"])), tier)
        results.append({
            "model": v["model"],
            "vehicle_type": v["vehicle_type"],
            "hourly_rate": v["hourly_rate"],
            "tier": tier,
            "delay_minutes": delay_minutes,
            "result": {k: str(val) for k, val in result.value.items()},
        })
        evidence.append({"type": "calculation", "tool": "late_fee", "steps": result.steps, "citations": _cite(result)})

    data = {"vehicle_query": vehicle_model or vehicle_type, "delay_minutes": delay_minutes, "tier": tier, "results": results}
    return ToolResult(ok=True, data=data, evidence=evidence)


def battery_fee_hypothetical(
    con: sqlite3.Connection,
    vehicle_model: str | None,
    vehicle_type: str | None,
    battery_pct: int | None,
) -> ToolResult:
    """A direct 'what would the low-battery fee be' question for an EV,
    not tied to any real booking."""
    if battery_pct is None:
        return ToolResult(ok=False, message=CLARIFY_BATTERY_PCT_MESSAGE)

    vehicles = _find_vehicles(con, vehicle_model, vehicle_type)
    if not vehicles:
        return ToolResult(ok=False, message=CLARIFY_VEHICLE_MESSAGE)

    seen_types = []
    evidence = []
    results = []
    for v in vehicles:
        if v["vehicle_type"] in seen_types:
            continue
        seen_types.append(v["vehicle_type"])
        result = calc.battery_fee(v["vehicle_type"], battery_pct)
        results.append({
            "vehicle_type": v["vehicle_type"],
            "model": v["model"],
            "battery_pct": battery_pct,
            "result": None if result.value is None else {k: str(val) for k, val in result.value.items()},
        })
        evidence.append({"type": "calculation", "tool": "battery_fee", "steps": result.steps, "citations": _cite(result)})

    data = {"vehicle_query": vehicle_model or vehicle_type, "battery_pct": battery_pct, "results": results}
    return ToolResult(ok=True, data=data, evidence=evidence)


def _cite(result: calc.CalcResult) -> list[dict]:
    return [{"doc_id": c.doc_id, "title": c.title, "section": c.section} for c in result.citations]


def calc_hours_before(reference_time, scheduled_start_str: str) -> Decimal:
    return hours_between_exact(reference_time, parse_utc(scheduled_start_str))
