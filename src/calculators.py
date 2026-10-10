"""
Pure calculation functions for all money/time rules. No database or LLM
calls here. Every function returns a CalcResult: the number plus a
step-by-step working trail and the rule citation(s) used, so the composer
can show its work and the output is independently auditable.

Money uses Decimal throughout. Final amounts are quantized to paise (2 dp)
with ROUND_HALF_UP. Compare computed values against stored ones with a
tolerance of +-0.01 to absorb that rounding.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from src import rules_config as cfg
from src.clock import seconds_between

TWO_PLACES = Decimal("0.01")


def money(x: Decimal) -> Decimal:
    """Round to paise using round-half-up (documented rounding rule)."""
    return x.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def approx_equal(a: Decimal, b: Decimal, tolerance: Decimal = Decimal("0.01")) -> bool:
    return abs(a - b) <= tolerance


@dataclass
class CalcResult:
    value: Decimal
    steps: list[str] = field(default_factory=list)
    citations: list[cfg.Citation] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Policy version
# ---------------------------------------------------------------------------

def policy_version(booked_at_utc: str) -> CalcResult:
    """Which cancellation/refund policy version applies, decided by booked_at (UTC text)."""
    is_v2 = booked_at_utc >= cfg.POLICY_V2_CUTOFF_UTC
    version = "v2" if is_v2 else "v1"
    doc_id = "RW-POL-03" if is_v2 else "RW-POL-02"
    steps = [
        f"booked_at (UTC) = {booked_at_utc}",
        f"v2 cutoff (UTC) = {cfg.POLICY_V2_CUTOFF_UTC} (= 1 Jul 2026 00:00 IST)",
        f"booked_at {'>=' if is_v2 else '<'} cutoff -> policy {version} ({doc_id})",
    ]
    return CalcResult(value=version, steps=steps, citations=[cfg.CITE_VERSION_CUTOFF])


# ---------------------------------------------------------------------------
# Refund
# ---------------------------------------------------------------------------

def refund(
    booking_status: str,
    version: str,
    hours_before_pickup: Decimal,
    rental_paid: Decimal,
    gst_paid: Decimal,
) -> CalcResult:
    """Refund for a cancellation, given the policy version and hours before
    scheduled pickup at the time of cancellation (or now, for a hypothetical).

    rental_paid / gst_paid = sum of SUCCESS BOOKING payments (amount / gst_amount).
    """
    steps = []
    citations = [cfg.CITE_REFUND_TIMELINE, cfg.CITE_DEPOSIT_NOT_IN_REFUND_SCHEDULE]

    if booking_status == "CNL_S":
        pct = Decimal("1.00")
        steps.append("booking_status = CNL_S (cancelled by RideWise) -> 100% refund always")
        citations.append(cfg.CITE_CNL_S_FULL_REFUND)
    elif booking_status == "NSH":
        pct = Decimal("0.00")
        steps.append("booking_status = NSH (no-show) -> no refund")
        citations.append(cfg.CITE_NO_SHOW_NO_REFUND)
    elif booking_status != "CNL_U":
        # UPC (hypothetical "if I cancel now"), ONG, CMP are not actual cancellations.
        slabs = cfg.REFUND_SLABS_V1 if version == "v1" else cfg.REFUND_SLABS_V2
        pct = _slab_lookup(hours_before_pickup, slabs)
        steps.append(f"hypothetical cancellation now; hours before scheduled pickup = {hours_before_pickup}")
        steps.append(f"policy {version} slab -> {pct * 100}% refund of rental charge")
        citations.append(cfg.CITE_REFUND_V1 if version == "v1" else cfg.CITE_REFUND_V2)
    else:
        slabs = cfg.REFUND_SLABS_V1 if version == "v1" else cfg.REFUND_SLABS_V2
        pct = _slab_lookup(hours_before_pickup, slabs)
        steps.append(f"hours before scheduled pickup at cancellation = {hours_before_pickup}")
        steps.append(f"policy {version} slab -> {pct * 100}% refund of rental charge")
        citations.append(cfg.CITE_REFUND_V1 if version == "v1" else cfg.CITE_REFUND_V2)

    refund_rental = money(rental_paid * pct)
    refund_gst = money(gst_paid * pct)
    total = money(refund_rental + refund_gst)
    steps.append(f"rental_paid={rental_paid}, gst_paid={gst_paid}")
    steps.append(f"refund_rental = {rental_paid} x {pct} = {refund_rental}")
    steps.append(f"refund_gst = {gst_paid} x {pct} = {refund_gst}")
    steps.append(f"total refund = {total} (security deposit, if any, is separate and not part of this)")

    return CalcResult(
        value={"pct": pct, "refund_rental": refund_rental, "refund_gst": refund_gst, "total": total},
        steps=steps,
        citations=citations,
    )


def _slab_lookup(hours_before: Decimal, slabs: list[tuple[Decimal, Decimal]]) -> Decimal:
    for threshold, pct in slabs:
        if hours_before >= threshold:
            return pct
    return slabs[-1][1]


# ---------------------------------------------------------------------------
# Late return fee
# ---------------------------------------------------------------------------

def late_fee(scheduled_end_utc: datetime, actual_return_utc: datetime, hourly_rate: Decimal, tier: str) -> CalcResult:
    """Late fee for a return after scheduled_end. Grace (GOLD only) only
    removes the fee entirely if lateness <= grace; beyond that the FULL
    lateness is charged (no partial grace deduction)."""
    lateness_seconds = seconds_between(scheduled_end_utc, actual_return_utc)
    steps = [f"scheduled_end={scheduled_end_utc}, actual_return={actual_return_utc}, lateness_seconds={lateness_seconds}"]

    if lateness_seconds <= 0:
        steps.append("return at or before scheduled_end -> no late fee")
        return CalcResult(value={"fee": Decimal("0.00"), "gst": Decimal("0.00"), "total": Decimal("0.00")}, steps=steps, citations=[cfg.CITE_LATE_FEE])

    grace_minutes = cfg.TIER_GRACE_MINUTES.get(tier, 0)
    grace_seconds = grace_minutes * 60
    steps.append(f"tier={tier}, grace={grace_minutes} min ({cfg.CITE_TIER_GRACE.doc_id})")

    if lateness_seconds <= grace_seconds:
        steps.append(f"lateness_seconds ({lateness_seconds}) <= grace_seconds ({grace_seconds}) -> no late fee")
        return CalcResult(value={"fee": Decimal("0.00"), "gst": Decimal("0.00"), "total": Decimal("0.00")}, steps=steps, citations=[cfg.CITE_LATE_FEE, cfg.CITE_TIER_GRACE])

    billed_hours = math.ceil(Decimal(lateness_seconds) / Decimal(3600))
    steps.append(f"lateness exceeds grace -> full lateness charged; billed_hours = ceil({lateness_seconds}/3600) = {billed_hours}")

    fee = money(Decimal(billed_hours) * cfg.LATE_FEE_MULTIPLIER * hourly_rate)
    gst = money(fee * cfg.GST_RATE)
    total = money(fee + gst)
    steps.append(f"fee = {billed_hours} x {cfg.LATE_FEE_MULTIPLIER} x {hourly_rate} = {fee}")
    steps.append(f"gst = {fee} x {cfg.GST_RATE} = {gst}")
    steps.append(f"total late fee = {total}")

    return CalcResult(
        value={"fee": fee, "gst": gst, "total": total, "billed_hours": billed_hours},
        steps=steps,
        citations=[cfg.CITE_LATE_FEE, cfg.CITE_TIER_GRACE, cfg.CITE_GST],
    )


# ---------------------------------------------------------------------------
# EV low-battery fee
# ---------------------------------------------------------------------------

def battery_fee(vehicle_type: str, return_battery_pct: int | None) -> CalcResult:
    steps = [f"vehicle_type={vehicle_type}, return_battery_pct={return_battery_pct}"]

    if vehicle_type not in cfg.EV_VEHICLE_TYPES:
        steps.append("not an EV vehicle type -> no battery fee applies")
        return CalcResult(value={"fee": Decimal("0.00"), "gst": Decimal("0.00"), "total": Decimal("0.00")}, steps=steps, citations=[cfg.CITE_BATTERY_FEE])

    if return_battery_pct is None:
        steps.append("return_battery_pct is missing -> cannot determine battery fee")
        return CalcResult(value=None, steps=steps, citations=[cfg.CITE_BATTERY_FEE], assumptions=["return_battery_pct not recorded for this booking"])

    if return_battery_pct < cfg.EV_LOW_BATTERY_THRESHOLD_PCT:
        fee = cfg.EV_LOW_BATTERY_FLAT_FEE
        gst = money(fee * cfg.GST_RATE)
        total = money(fee + gst)
        steps.append(f"{return_battery_pct}% < {cfg.EV_LOW_BATTERY_THRESHOLD_PCT}% -> flat fee {fee} + GST {gst} = {total}")
        return CalcResult(value={"fee": fee, "gst": gst, "total": total}, steps=steps, citations=[cfg.CITE_BATTERY_FEE, cfg.CITE_GST])

    steps.append(f"{return_battery_pct}% >= {cfg.EV_LOW_BATTERY_THRESHOLD_PCT}% -> no fee (exactly 10% is not below 10%)")
    return CalcResult(value={"fee": Decimal("0.00"), "gst": Decimal("0.00"), "total": Decimal("0.00")}, steps=steps, citations=[cfg.CITE_BATTERY_FEE])


# ---------------------------------------------------------------------------
# Rental charge
# ---------------------------------------------------------------------------

def rental_charge(hours: Decimal, hourly_rate: Decimal, daily_rate: Decimal) -> CalcResult:
    """Whole-hour booked duration -> rental charge (excl. GST).

    Full 24h blocks at daily_rate; remaining hours at hourly_rate, but the
    remainder never exceeds one daily_rate (capped).
    """
    steps = [f"hours={hours}, hourly_rate={hourly_rate}, daily_rate={daily_rate}"]
    full_days = int(hours // 24)
    remaining_hours = hours - (full_days * 24)
    steps.append(f"full_days = {hours}//24 = {full_days}, remaining_hours = {remaining_hours}")

    day_charge = money(Decimal(full_days) * daily_rate)
    hourly_charge = money(remaining_hours * hourly_rate)
    capped_hourly = min(hourly_charge, daily_rate)
    if hourly_charge != capped_hourly:
        steps.append(f"remaining-hours charge {hourly_charge} capped at one daily_rate {daily_rate}")
    total = money(day_charge + capped_hourly)
    steps.append(f"day_charge = {full_days} x {daily_rate} = {day_charge}")
    steps.append(f"remaining-hours charge = min({remaining_hours} x {hourly_rate}, {daily_rate}) = {capped_hourly}")
    steps.append(f"total rental charge (excl. GST) = {day_charge} + {capped_hourly} = {total}")

    return CalcResult(value=total, steps=steps, citations=[cfg.CITE_RENTAL_CHARGE])


# ---------------------------------------------------------------------------
# Damage
# ---------------------------------------------------------------------------

def damage_chargeable(claim_status: str, assessed_cost: Decimal) -> CalcResult:
    steps = [f"claim_status={claim_status}, assessed_cost={assessed_cost}"]
    if claim_status in cfg.DAMAGE_CHARGEABLE_STATUSES:
        steps.append(f"status is CHARGED -> customer charged the assessed cost {assessed_cost}")
        return CalcResult(value=assessed_cost, steps=steps, citations=[cfg.CITE_DAMAGE])
    steps.append(f"status is {claim_status} -> not charged (yet, or at all)")
    return CalcResult(value=Decimal("0.00"), steps=steps, citations=[cfg.CITE_DAMAGE])


# ---------------------------------------------------------------------------
# Security deposit (informational — never shown as "missing" when absent)
# ---------------------------------------------------------------------------

def deposit_amount(vehicle_type: str, hours: Decimal) -> CalcResult:
    steps = [f"vehicle_type={vehicle_type}, hours={hours}"]
    if vehicle_type in ("BIKE", "EV_BIKE"):
        amt = cfg.DEPOSIT_BIKE_EV_BIKE
        steps.append(f"{vehicle_type} -> deposit {amt} may be collected for any rental")
    elif vehicle_type in ("SCOOTER", "EV_SCOOTER"):
        if hours >= cfg.DEPOSIT_SCOOTER_MIN_HOURS:
            amt = cfg.DEPOSIT_SCOOTER_EV_SCOOTER
            steps.append(f"{vehicle_type}, hours >= {cfg.DEPOSIT_SCOOTER_MIN_HOURS} -> deposit {amt} may be collected")
        else:
            amt = Decimal("0.00")
            steps.append(f"{vehicle_type}, hours < {cfg.DEPOSIT_SCOOTER_MIN_HOURS} -> no deposit specified")
    else:
        amt = Decimal("0.00")
        steps.append("unknown vehicle_type -> cannot determine deposit")
    steps.append("deposit carries no GST and is not shown in RideWise payment records once returned")
    return CalcResult(value=amt, steps=steps, citations=[cfg.CITE_DEPOSIT, cfg.CITE_DEPOSIT_NOT_IN_REFUND_SCHEDULE])
