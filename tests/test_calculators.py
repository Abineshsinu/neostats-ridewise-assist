"""Unit tests for pure calculators, focused on documented boundary values."""
from decimal import Decimal

from src import calculators as calc
from src.clock import parse_utc


# ---------------------------------------------------------------------------
# policy_version
# ---------------------------------------------------------------------------

def test_policy_version_before_cutoff_is_v1():
    assert calc.policy_version("2026-06-30 18:29:59").value == "v1"


def test_policy_version_at_cutoff_is_v2():
    assert calc.policy_version("2026-06-30 18:30:00").value == "v2"


def test_policy_version_b1164_b1165_are_v2_despite_utc_date_30_jun():
    # Booked after midnight IST on 1 Jul 2026, i.e. UTC >= 18:30:00 on 30 Jun.
    assert calc.policy_version("2026-06-30 19:33:00").value == "v2"
    assert calc.policy_version("2026-06-30 20:15:00").value == "v2"


# ---------------------------------------------------------------------------
# refund — v1 slab edges
# ---------------------------------------------------------------------------

def test_refund_v1_exactly_24h_is_100_pct():
    r = calc.refund("CNL_U", "v1", Decimal(24), Decimal(500), Decimal(90))
    assert r.value["pct"] == Decimal("1.00")
    assert r.value["total"] == Decimal("590.00")


def test_refund_v1_just_under_24h_is_50_pct():
    r = calc.refund("CNL_U", "v1", Decimal("23.999"), Decimal(500), Decimal(90))
    assert r.value["pct"] == Decimal("0.50")


def test_refund_v1_exactly_6h_is_50_pct():
    r = calc.refund("CNL_U", "v1", Decimal(6), Decimal(500), Decimal(90))
    assert r.value["pct"] == Decimal("0.50")


def test_refund_v1_just_under_6h_is_0_pct():
    r = calc.refund("CNL_U", "v1", Decimal("5.999"), Decimal(500), Decimal(90))
    assert r.value["pct"] == Decimal("0.00")


def test_refund_v1_worked_example_from_policy():
    # RW-POL-02 §5 example: ₹500 paid, cancelled 12h before pickup -> 50% = ₹250 + GST ₹45
    r = calc.refund("CNL_U", "v1", Decimal(12), Decimal(500), Decimal(90))
    assert r.value["refund_rental"] == Decimal("250.00")
    assert r.value["refund_gst"] == Decimal("45.00")


# ---------------------------------------------------------------------------
# refund — v2 slab edges
# ---------------------------------------------------------------------------

def test_refund_v2_exactly_48h_is_100_pct():
    r = calc.refund("CNL_U", "v2", Decimal(48), Decimal(500), Decimal(90))
    assert r.value["pct"] == Decimal("1.00")


def test_refund_v2_just_under_48h_is_75_pct():
    r = calc.refund("CNL_U", "v2", Decimal("47.999"), Decimal(500), Decimal(90))
    assert r.value["pct"] == Decimal("0.75")


def test_refund_v2_exactly_12h_is_75_pct():
    r = calc.refund("CNL_U", "v2", Decimal(12), Decimal(500), Decimal(90))
    assert r.value["pct"] == Decimal("0.75")


def test_refund_v2_just_under_12h_is_25_pct():
    r = calc.refund("CNL_U", "v2", Decimal("11.999"), Decimal(500), Decimal(90))
    assert r.value["pct"] == Decimal("0.25")


def test_refund_v2_exactly_2h_is_25_pct():
    r = calc.refund("CNL_U", "v2", Decimal(2), Decimal(500), Decimal(90))
    assert r.value["pct"] == Decimal("0.25")


def test_refund_v2_just_under_2h_is_0_pct():
    r = calc.refund("CNL_U", "v2", Decimal("1.999"), Decimal(500), Decimal(90))
    assert r.value["pct"] == Decimal("0.00")


# ---------------------------------------------------------------------------
# refund — status overrides
# ---------------------------------------------------------------------------

def test_refund_cnl_s_always_100_pct_regardless_of_timing():
    r = calc.refund("CNL_S", "v1", Decimal(0), Decimal(500), Decimal(90))
    assert r.value["pct"] == Decimal("1.00")


def test_refund_no_show_is_zero():
    r = calc.refund("NSH", "v2", Decimal(100), Decimal(500), Decimal(90))
    assert r.value["pct"] == Decimal("0.00")


# ---------------------------------------------------------------------------
# late_fee — tier grace boundary (GOLD 30 vs 31 minutes) + part-hour rounding
# ---------------------------------------------------------------------------

def test_late_fee_gold_exactly_30_min_no_fee():
    sched = parse_utc("2026-10-01 10:00:00")
    actual = parse_utc("2026-10-01 10:30:00")
    r = calc.late_fee(sched, actual, Decimal(100), "GOLD")
    assert r.value["total"] == Decimal("0.00")


def test_late_fee_gold_31_min_charges_full_lateness_not_partial():
    sched = parse_utc("2026-10-01 10:00:00")
    actual = parse_utc("2026-10-01 10:31:00")
    r = calc.late_fee(sched, actual, Decimal(100), "GOLD")
    # 31 minutes rounds up to 1 full hour, fee = 1 x 1.5 x 100 = 150, GST 18% = 27, total 177
    assert r.value["fee"] == Decimal("150.00")
    assert r.value["total"] == Decimal("177.00")


def test_late_fee_standard_no_grace_5_min_bills_1_hour():
    sched = parse_utc("2026-10-01 10:00:00")
    actual = parse_utc("2026-10-01 10:05:00")
    r = calc.late_fee(sched, actual, Decimal(100), "STANDARD")
    assert r.value["fee"] == Decimal("150.00")  # matches RW-POL-04 §1.4 example


def test_late_fee_standard_59_min_bills_1_hour():
    sched = parse_utc("2026-10-01 10:00:00")
    actual = parse_utc("2026-10-01 10:59:00")
    r = calc.late_fee(sched, actual, Decimal(100), "STANDARD")
    assert r.value["fee"] == Decimal("150.00")


def test_late_fee_standard_1h01m_bills_2_hours():
    sched = parse_utc("2026-10-01 10:00:00")
    actual = parse_utc("2026-10-01 11:01:00")
    r = calc.late_fee(sched, actual, Decimal(100), "STANDARD")
    assert r.value["fee"] == Decimal("300.00")  # matches RW-POL-04 §1.4 example


def test_late_fee_standard_3h15m_bills_4_hours():
    sched = parse_utc("2026-10-01 10:00:00")
    actual = parse_utc("2026-10-01 13:15:00")
    r = calc.late_fee(sched, actual, Decimal(100), "STANDARD")
    assert r.value["fee"] == Decimal("600.00")  # matches RW-POL-04 §1.4 example


def test_late_fee_not_late_is_zero():
    sched = parse_utc("2026-10-01 10:00:00")
    actual = parse_utc("2026-10-01 09:59:00")
    r = calc.late_fee(sched, actual, Decimal(100), "STANDARD")
    assert r.value["total"] == Decimal("0.00")


# ---------------------------------------------------------------------------
# battery_fee — 9% vs 10% boundary
# ---------------------------------------------------------------------------

def test_battery_fee_9_pct_charges_flat_fee_plus_gst():
    r = calc.battery_fee("EV_SCOOTER", 9)
    assert r.value["fee"] == Decimal("150.00")
    assert r.value["gst"] == Decimal("27.00")
    assert r.value["total"] == Decimal("177.00")


def test_battery_fee_exactly_10_pct_no_fee():
    r = calc.battery_fee("EV_BIKE", 10)
    assert r.value["total"] == Decimal("0.00")


def test_battery_fee_non_ev_vehicle_no_fee():
    r = calc.battery_fee("BIKE", 5)
    assert r.value["total"] == Decimal("0.00")


def test_battery_fee_missing_pct_is_indeterminate():
    r = calc.battery_fee("EV_BIKE", None)
    assert r.value is None


# ---------------------------------------------------------------------------
# rental_charge — worked examples from the Rental Agreement
# ---------------------------------------------------------------------------

def test_rental_charge_4_hours():
    r = calc.rental_charge(Decimal(4), Decimal(80), Decimal(700))
    assert r.value == Decimal("320.00")


def test_rental_charge_10_hours_capped_at_daily_rate():
    r = calc.rental_charge(Decimal(10), Decimal(80), Decimal(700))
    assert r.value == Decimal("700.00")


def test_rental_charge_24_hours():
    r = calc.rental_charge(Decimal(24), Decimal(80), Decimal(700))
    assert r.value == Decimal("700.00")


def test_rental_charge_27_hours():
    r = calc.rental_charge(Decimal(27), Decimal(80), Decimal(700))
    assert r.value == Decimal("940.00")


# ---------------------------------------------------------------------------
# damage_chargeable
# ---------------------------------------------------------------------------

def test_damage_charged_status_charges_assessed_cost():
    r = calc.damage_chargeable("CHARGED", Decimal("1200.00"))
    assert r.value == Decimal("1200.00")


def test_damage_open_not_charged():
    r = calc.damage_chargeable("OPEN", Decimal("1200.00"))
    assert r.value == Decimal("0.00")


def test_damage_disputed_not_charged():
    r = calc.damage_chargeable("DISPUTED", Decimal("1200.00"))
    assert r.value == Decimal("0.00")


def test_damage_waived_not_charged():
    r = calc.damage_chargeable("WAIVED", Decimal("1200.00"))
    assert r.value == Decimal("0.00")
