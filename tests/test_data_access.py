"""
Vetted tool tests, including the core security property: a booking_id
that does not exist and a booking_id that belongs to a different customer
must produce the exact same refusal from this customer's sandbox. The
caller must never be able to tell the two cases apart.
"""
from decimal import Decimal

from src import data_access as da
from src.sandbox import build_customer_sandbox


def test_resolve_booking_same_refusal_for_nonexistent_and_other_customer_booking():
    cust1 = build_customer_sandbox("CUST0001")
    # B-0001 belongs to CUST0001 themselves — sanity check it resolves.
    assert da.resolve_booking(cust1, "B-0001") is not None

    # A booking id that plausibly belongs to another customer (not copied
    # into this sandbox at all) and one that doesn't exist anywhere must
    # both resolve to None, indistinguishably.
    other_customers_booking = da.resolve_booking(cust1, "B-1700")  # exists, but not CUST0001's
    nonexistent_booking = da.resolve_booking(cust1, "B-9999999")
    assert other_customers_booking is None
    assert nonexistent_booking is None


def test_booking_detail_same_message_for_both_cases():
    cust1 = build_customer_sandbox("CUST0001")
    r1 = da.booking_detail(cust1, "B-1700")
    r2 = da.booking_detail(cust1, "B-9999999")
    assert not r1.ok and not r2.ok
    assert r1.message == r2.message == da.NOT_FOUND_MESSAGE


def test_booking_detail_own_booking_succeeds():
    cust1 = build_customer_sandbox("CUST0001")
    result = da.booking_detail(cust1, "B-0001")
    assert result.ok
    assert result.data["booking"]["booking_id"] == "B-0001"
    assert result.data["vehicle"] is not None
    assert {"type": "data", "table": "bookings", "row_ids": ["B-0001"]} in result.evidence


def test_list_my_bookings_returns_only_own_bookings():
    cust1 = build_customer_sandbox("CUST0001")
    result = da.list_my_bookings(cust1)
    assert result.ok
    ids = {b["booking_id"] for b in result.data}
    assert ids == {"B-0001", "B-0554", "B-1653"}


def test_list_my_bookings_includes_code_computed_ist_times():
    """Timezone conversion must happen in code, never left for the LLM to
    guess — a prior bug had the composer relabel raw UTC as "(IST)"
    without converting. B-0001's scheduled_start is 2026-08-15 04:30:00
    UTC, which is 10:00 IST (+5:30)."""
    cust1 = build_customer_sandbox("CUST0001")
    result = da.list_my_bookings(cust1)
    booking = next(b for b in result.data if b["booking_id"] == "B-0001")
    assert booking["scheduled_start"] == "2026-08-15 04:30:00"
    assert booking["scheduled_start_ist"] == "2026-08-15 10:00 IST"


def test_payments_for_booking_requires_ownership():
    cust1 = build_customer_sandbox("CUST0001")
    result = da.payments_for_booking(cust1, "B-1700")
    assert not result.ok
    assert result.message == da.NOT_FOUND_MESSAGE


def test_payments_for_booking_returns_rows_with_evidence():
    cust1 = build_customer_sandbox("CUST0001")
    result = da.payments_for_booking(cust1, "B-0001")
    assert result.ok
    assert len(result.data) == 1
    assert result.data[0]["payment_id"] == "PAY00001"


def test_refund_estimate_upcoming_booking_is_hypothetical():
    cust1 = build_customer_sandbox("CUST0001")
    result = da.refund_estimate(cust1, "B-1653")  # UPC booking
    assert result.ok
    assert result.data["booking_status"] == "UPC"
    assert "hypothetical" in (result.message or "").lower()
    assert Decimal(result.data["rental_paid"]) == Decimal("480")  # two 240 partial payments


def test_refund_estimate_unknown_booking_refuses():
    cust1 = build_customer_sandbox("CUST0001")
    result = da.refund_estimate(cust1, "B-9999999")
    assert not result.ok
    assert result.message == da.NOT_FOUND_MESSAGE


def test_explain_charge_damage_booking_matches_recorded_penalty():
    cust1 = build_customer_sandbox("CUST0001")
    result = da.explain_charge(cust1, "B-0554")
    assert result.ok
    assert len(result.data["recorded_penalty_payments"]) == 1
    assert result.data["recorded_penalty_payments"][0]["remarks"] == "Damage charge DMG0046"
    damage_checks = [c for c in result.data["recomputed_checks"] if c["check"] == "damage"]
    assert damage_checks
    assert damage_checks[0]["report_id"] == "DMG0046"


def test_explain_charge_unknown_booking_refuses():
    cust1 = build_customer_sandbox("CUST0001")
    result = da.explain_charge(cust1, "B-9999999")
    assert not result.ok
    assert result.message == da.NOT_FOUND_MESSAGE


def test_late_fee_hypothetical_by_model_gold_31_min_charges_full_lateness():
    """Direct hypothetical: GOLD tier, 31 minutes late -> full lateness
    charged (not reduced by the 30-min grace), matching Annexure A."""
    cust1 = build_customer_sandbox("CUST0001")
    result = da.late_fee_hypothetical(cust1, "Honda Activa 6G", None, 31, "GOLD")
    assert result.ok
    r = result.data["results"][0]
    assert r["model"] == "Honda Activa 6G"
    assert Decimal(r["result"]["fee"]) == Decimal("90.00")  # 1hr x 1.5 x 60


def test_late_fee_hypothetical_gold_exactly_30_min_no_fee():
    cust1 = build_customer_sandbox("CUST0001")
    result = da.late_fee_hypothetical(cust1, "Honda Activa 6G", None, 30, "GOLD")
    assert result.ok
    assert Decimal(result.data["results"][0]["result"]["total"]) == Decimal("0.00")


def test_late_fee_hypothetical_by_type_returns_multiple_models():
    cust1 = build_customer_sandbox("CUST0001")
    result = da.late_fee_hypothetical(cust1, None, "SCOOTER", 10, "STANDARD")
    assert result.ok
    assert len(result.data["results"]) > 1
    assert all(r["vehicle_type"] == "SCOOTER" for r in result.data["results"])


def test_late_fee_hypothetical_unknown_vehicle_asks_for_clarification():
    cust1 = build_customer_sandbox("CUST0001")
    result = da.late_fee_hypothetical(cust1, "Nonexistent Model XYZ", None, 10, "STANDARD")
    assert not result.ok
    assert result.message == da.CLARIFY_VEHICLE_MESSAGE


def test_battery_fee_hypothetical_9_pct_charges_flat_fee():
    cust1 = build_customer_sandbox("CUST0001")
    result = da.battery_fee_hypothetical(cust1, "Ather 450X", None, 9)
    assert result.ok
    assert Decimal(result.data["results"][0]["result"]["total"]) == Decimal("177.00")


def test_battery_fee_hypothetical_exactly_10_pct_no_fee():
    cust1 = build_customer_sandbox("CUST0001")
    result = da.battery_fee_hypothetical(cust1, "Ather 450X", None, 10)
    assert result.ok
    assert Decimal(result.data["results"][0]["result"]["total"]) == Decimal("0.00")


def test_battery_fee_hypothetical_non_ev_type_reports_no_fee():
    cust1 = build_customer_sandbox("CUST0001")
    result = da.battery_fee_hypothetical(cust1, "Honda Activa 6G", None, 5)
    assert result.ok
    assert Decimal(result.data["results"][0]["result"]["total"]) == Decimal("0.00")


def test_battery_fee_hypothetical_missing_pct_asks_for_clarification():
    cust1 = build_customer_sandbox("CUST0001")
    result = da.battery_fee_hypothetical(cust1, "Ather 450X", None, None)
    assert not result.ok
    assert result.message == da.CLARIFY_BATTERY_PCT_MESSAGE


def test_cross_customer_isolation_end_to_end_for_all_tools():
    """A booking that genuinely exists (for another customer) must be
    unreachable through every vetted tool from this customer's sandbox."""
    cust1 = build_customer_sandbox("CUST0001")
    other_booking = "B-1700"
    assert not da.booking_detail(cust1, other_booking).ok
    assert not da.payments_for_booking(cust1, other_booking).ok
    assert not da.refund_estimate(cust1, other_booking).ok
    assert not da.explain_charge(cust1, other_booking).ok
