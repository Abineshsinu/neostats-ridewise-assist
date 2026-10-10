"""
Data reconciliation tests: recompute every chargeable amount from the raw
database using the pure calculators, and compare against what's actually
stored in payments. Expect zero mismatches except the two known, documented
exceptions:
  - B-1709, B-1729: CNL_U v2 cancellations with no refund row recorded yet
    (refund owed, not yet recorded).
  - B-0006: EV bike with a 500 pending deposit (policy says bikes/EV bikes
    should be 1000) — a documented data anomaly, not a reconciliation bug.

Runs against ridewise.db strictly read-only.
"""
from decimal import Decimal

import pytest

from src import calculators as calc
from src.clock import parse_utc
from src.db import get_connection

KNOWN_EXCEPTIONS_REFUND = {"B-1709", "B-1729"}
KNOWN_EXCEPTIONS_DEPOSIT = {"B-0006"}


@pytest.fixture(scope="module")
def con():
    c = get_connection()
    yield c
    c.close()


def test_late_fee_payments_reconcile(con):
    cur = con.cursor()
    cur.execute(
        """
        SELECT p.payment_id, p.booking_id, p.amount, p.gst_amount,
               b.scheduled_end, b.actual_return_at, v.hourly_rate, cu.customer_tier
        FROM payments p
        JOIN bookings b ON b.booking_id = p.booking_id
        JOIN vehicles v ON v.vehicle_id = b.vehicle_id
        JOIN customers cu ON cu.customer_id = b.customer_id
        WHERE p.payment_type = 'PENALTY'
          AND (p.remarks LIKE 'Late return%')
        """
    )
    rows = cur.fetchall()
    assert len(rows) > 0, "expected at least one late-fee payment to reconcile"

    mismatches = []
    for r in rows:
        sched = parse_utc(r["scheduled_end"])
        actual = parse_utc(r["actual_return_at"])
        result = calc.late_fee(sched, actual, Decimal(str(r["hourly_rate"])), r["customer_tier"])
        computed_fee = result.value["fee"]
        computed_gst = result.value["gst"]
        stored_fee = Decimal(str(r["amount"]))
        stored_gst = Decimal(str(r["gst_amount"]))
        if not (calc.approx_equal(computed_fee, stored_fee) and calc.approx_equal(computed_gst, stored_gst)):
            mismatches.append((r["booking_id"], computed_fee, stored_fee, computed_gst, stored_gst))

    assert mismatches == [], f"late fee mismatches: {mismatches}"


def test_battery_fee_payments_reconcile(con):
    cur = con.cursor()
    cur.execute(
        """
        SELECT p.payment_id, p.booking_id, p.amount, p.gst_amount,
               v.vehicle_type, b.return_battery_pct
        FROM payments p
        JOIN bookings b ON b.booking_id = p.booking_id
        JOIN vehicles v ON v.vehicle_id = b.vehicle_id
        WHERE p.payment_type = 'PENALTY'
          AND (p.remarks LIKE '%battery%')
        """
    )
    rows = cur.fetchall()
    assert len(rows) > 0

    mismatches = []
    for r in rows:
        result = calc.battery_fee(r["vehicle_type"], r["return_battery_pct"])
        if result.value is None:
            mismatches.append((r["booking_id"], "battery_pct missing", r["amount"]))
            continue
        stored_fee = Decimal(str(r["amount"]))
        stored_gst = Decimal(str(r["gst_amount"]))
        if not (calc.approx_equal(result.value["fee"], stored_fee) and calc.approx_equal(result.value["gst"], stored_gst)):
            mismatches.append((r["booking_id"], result.value, stored_fee, stored_gst))

    assert mismatches == [], f"battery fee mismatches: {mismatches}"


def test_damage_charged_payments_reconcile(con):
    cur = con.cursor()
    cur.execute(
        """
        SELECT payment_id, booking_id, amount, remarks
        FROM payments
        WHERE payment_type = 'PENALTY' AND remarks LIKE 'Damage charge%'
        """
    )
    rows = cur.fetchall()
    assert len(rows) > 0

    mismatches = []
    for r in rows:
        report_id = r["remarks"].replace("Damage charge ", "").strip()
        cur2 = con.cursor()
        cur2.execute("SELECT assessed_cost, claim_status FROM damage_reports WHERE report_id = ?", (report_id,))
        dmg = cur2.fetchone()
        if dmg is None:
            mismatches.append((r["booking_id"], report_id, "damage report not found"))
            continue
        result = calc.damage_chargeable(dmg["claim_status"], Decimal(str(dmg["assessed_cost"])))
        stored = Decimal(str(r["amount"]))
        if not calc.approx_equal(result.value, stored):
            mismatches.append((r["booking_id"], report_id, result.value, stored))

    assert mismatches == [], f"damage charge mismatches: {mismatches}"


def test_recorded_refunds_reconcile(con):
    """Every recorded REFUND row should match a recomputed refund, except
    bookings with no refund row yet (B-1709, B-1729 — those are checked
    separately below for 'owed but not recorded')."""
    cur = con.cursor()
    cur.execute(
        """
        SELECT b.booking_id, b.booking_status, b.booked_at, b.scheduled_start, b.cancelled_at,
               r.amount AS refund_amount, r.gst_amount AS refund_gst
        FROM bookings b
        JOIN payments r ON r.booking_id = b.booking_id AND r.payment_type = 'REFUND'
        WHERE b.booking_status IN ('CNL_U', 'CNL_S')
        """
    )
    rows = cur.fetchall()
    assert len(rows) > 0

    mismatches = []
    for r in rows:
        cur2 = con.cursor()
        cur2.execute(
            "SELECT COALESCE(SUM(amount),0), COALESCE(SUM(gst_amount),0) FROM payments "
            "WHERE booking_id = ? AND payment_type = 'BOOKING' AND payment_status = 'SUCCESS'",
            (r["booking_id"],),
        )
        rental_paid, gst_paid = cur2.fetchone()
        rental_paid, gst_paid = Decimal(str(rental_paid)), Decimal(str(gst_paid))

        version = calc.policy_version(r["booked_at"]).value
        cancel_time = parse_utc(r["cancelled_at"]) if r["cancelled_at"] else None
        pickup_time = parse_utc(r["scheduled_start"])
        hours_before = max(Decimal(0), calc_hours(cancel_time, pickup_time)) if cancel_time else Decimal(0)

        result = calc.refund(r["booking_status"], version, hours_before, rental_paid, gst_paid)
        stored_total_rental = Decimal(str(r["refund_amount"]))
        stored_gst = Decimal(str(r["refund_gst"]))
        # Stored refund amount is negative (refunds are negative); compare magnitudes.
        if not (calc.approx_equal(result.value["refund_rental"], abs(stored_total_rental)) and
                calc.approx_equal(result.value["refund_gst"], abs(stored_gst))):
            mismatches.append((r["booking_id"], result.value, stored_total_rental, stored_gst))

    assert mismatches == [], f"refund mismatches: {mismatches}"


def calc_hours(earlier, later):
    from src.clock import hours_between_exact
    return hours_between_exact(earlier, later)


def test_b1709_b1729_refund_owed_but_not_recorded(con):
    cur = con.cursor()
    for bid in KNOWN_EXCEPTIONS_REFUND:
        cur.execute("SELECT booking_status FROM bookings WHERE booking_id = ?", (bid,))
        status = cur.fetchone()["booking_status"]
        assert status == "CNL_U"
        cur.execute("SELECT COUNT(*) AS c FROM payments WHERE booking_id = ? AND payment_type = 'REFUND'", (bid,))
        assert cur.fetchone()["c"] == 0, f"{bid} was expected to have no refund row yet"


def test_rental_charge_reconciles_for_bookings_with_successful_payment(con):
    cur = con.cursor()
    cur.execute(
        """
        SELECT b.booking_id, b.scheduled_start, b.scheduled_end, v.hourly_rate, v.daily_rate,
               SUM(p.amount) AS paid_amount
        FROM bookings b
        JOIN vehicles v ON v.vehicle_id = b.vehicle_id
        JOIN payments p ON p.booking_id = b.booking_id AND p.payment_type = 'BOOKING' AND p.payment_status = 'SUCCESS'
        GROUP BY b.booking_id
        """
    )
    rows = cur.fetchall()
    assert len(rows) > 0

    mismatches = []
    for r in rows:
        start = parse_utc(r["scheduled_start"])
        end = parse_utc(r["scheduled_end"])
        from src.clock import hours_between_exact
        hours = hours_between_exact(start, end)
        result = calc.rental_charge(hours, Decimal(str(r["hourly_rate"])), Decimal(str(r["daily_rate"])))
        stored = Decimal(str(r["paid_amount"]))
        if not calc.approx_equal(result.value, stored):
            mismatches.append((r["booking_id"], result.value, stored))

    # Allow a small number of mismatches to surface rather than hard-fail
    # the whole suite on an unexpected edge case; report them clearly.
    assert mismatches == [], f"rental charge mismatches ({len(mismatches)}): {mismatches[:10]}"
