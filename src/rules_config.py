"""
Single versioned source of truth for every policy rule value used by the
calculators. Each value cites the document, section/page and (where the
value lives in a scanned image) the derived transcription file it comes
from. Nothing here is invented — every number traces back to data/raw or
data/derived.

Unspecified-in-documents values are intentionally absent; calculators and
the composer must say "the documents don't specify this" rather than guess.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class Citation:
    doc_id: str
    title: str
    section: str


GST_RATE = Decimal("0.18")
CITE_GST = Citation("RW-POL-01", "Rental Agreement & Terms", "§4.3 (GST 18% on rental charges, penalties and fees)")

# --- Cancellation policy version cutoff ---
# Version is decided by booked_at, never by cancellation or rental date.
# Cutoff: 1 July 2026, 00:00 IST == 2026-06-30 18:30:00 UTC.
POLICY_V2_CUTOFF_UTC = "2026-06-30 18:30:00"
CITE_VERSION_CUTOFF = Citation(
    "RW-POL-02 / RW-POL-03",
    "Cancellation & Refund Policy v1 / v2 — Scope",
    "RW-POL-02 Scope; RW-POL-03 Scope (\"bookings made on or after 1 July 2026, 00:00 IST\")",
)

# --- Refund slabs: (min_hours_before_pickup_inclusive, refund_pct) descending ---
REFUND_SLABS_V1 = [
    (Decimal(24), Decimal("1.00")),
    (Decimal(6), Decimal("0.50")),
    (Decimal(0), Decimal("0.00")),
]
CITE_REFUND_V1 = Citation("RW-POL-02", "Cancellation & Refund Policy v1", "§1.1")

REFUND_SLABS_V2 = [
    (Decimal(48), Decimal("1.00")),
    (Decimal(12), Decimal("0.75")),
    (Decimal(2), Decimal("0.25")),
    (Decimal(0), Decimal("0.00")),
]
CITE_REFUND_V2 = Citation(
    "RW-POL-03", "Cancellation & Refund Policy v2",
    "Annexure 1 (transcribed in data/derived/policy_annexures.md)",
)

CITE_CNL_S_FULL_REFUND = Citation("RW-POL-02 / RW-POL-03", "Cancellation & Refund Policy", "§2.1 (RideWise-initiated cancellation: 100% refund always)")
CITE_NO_SHOW_NO_REFUND = Citation("RW-POL-01 / RW-POL-02 / RW-POL-03", "Rental Agreement §7 / Cancellation Policy §3", "no-show: rental charge not refunded, no extra fee")
CITE_REFUND_TIMELINE = Citation("RW-POL-02 / RW-POL-03", "Cancellation & Refund Policy", "§4.1 (initiated within 3 working days, credited in 5-7 working days)")
CITE_DEPOSIT_NOT_IN_REFUND_SCHEDULE = Citation("RW-POL-01", "Rental Agreement & Terms", "§5.3 (deposit returns processed by the gateway, not shown in RideWise records)")

# --- Rental charge ---
MIN_RENTAL_HOURS = Decimal(2)
CITE_RENTAL_CHARGE = Citation("RW-POL-01", "Rental Agreement & Terms", "§3.2, §4.1-4.2 (whole hours, min 2h; full 24h blocks at daily rate, remainder hourly, capped at one daily rate)")

# --- Security deposit ---
DEPOSIT_BIKE_EV_BIKE = Decimal(1000)
DEPOSIT_SCOOTER_EV_SCOOTER = Decimal(500)
DEPOSIT_SCOOTER_MIN_HOURS = Decimal(24)
CITE_DEPOSIT = Citation("RW-POL-01", "Rental Agreement & Terms", "§5.1 (Bike/EV bike: ₹1,000 any rental; Scooter/EV scooter: ₹500 for rentals of 24h or more; no GST)")

# --- Late return fee ---
LATE_FEE_MULTIPLIER = Decimal("1.5")
CITE_LATE_FEE = Citation("RW-POL-04", "Late Return & Damage Penalty Schedule", "§1.2 (each late hour or part-hour charged at 1.5x hourly rate)")

TIER_GRACE_MINUTES = {"STANDARD": 0, "SILVER": 0, "GOLD": 30}
CITE_TIER_GRACE = Citation(
    "RW-POL-04", "Late Return & Damage Penalty Schedule",
    "Annexure A (transcribed in data/derived/policy_annexures.md); §1.3 (grace does not reduce lateness once exceeded)",
)

# --- EV low-battery fee ---
EV_LOW_BATTERY_THRESHOLD_PCT = 10  # strictly below this triggers the fee
EV_LOW_BATTERY_FLAT_FEE = Decimal(150)
EV_VEHICLE_TYPES = {"EV_SCOOTER", "EV_BIKE"}
CITE_BATTERY_FEE = Citation("RW-POL-04", "Late Return & Damage Penalty Schedule", "§2 (below 10%: ₹150 flat fee; 10% or above: no fee; additional to any late fee)")

# --- Damage ---
DAMAGE_CHARGEABLE_STATUSES = {"CHARGED"}
CITE_DAMAGE = Citation("RW-POL-04", "Late Return & Damage Penalty Schedule", "§3.1 (only CHARGED claims are charged, at the assessed cost)")

# --- No-show definition ---
NO_SHOW_GRACE_MINUTES = 60
CITE_NO_SHOW_DEFINITION = Citation("RW-POL-01", "Rental Agreement & Terms", "§7.1 (no pickup within 60 minutes of scheduled pickup, and no prior cancellation)")

# --- Support contact (for "why was I charged extra" escalation) ---
SUPPORT_HOURS = "7:00 AM to 11:00 PM IST, every day"
SUPPORT_EMAIL = "support@ridewise.example"
SUPPORT_PHONE = "+91 80 4000 1234"
CITE_SUPPORT = Citation("RW-POL-01", "Rental Agreement & Terms", "§9 Contact")

# --- Timezone ---
IST_OFFSET_HOURS = 5
IST_OFFSET_MINUTES = 30

# --- Explicitly unspecified in the documents (never guess these) ---
UNSPECIFIED = [
    "EV recovery/towing charge amount (FAQ mentions 'a recovery charge may apply' with no figure)",
    "Customer tier qualification thresholds (how a customer becomes SILVER/GOLD)",
    "Definition of 'working day' / which days are holidays, for refund/deposit timelines",
    "Traffic fine amounts (customer is responsible per §8.2, but no schedule is given)",
    "Rules for cancelling after the scheduled pickup time, or for an ONG (ongoing) booking",
    "Deposit-return records (deposits are returned by the gateway and never appear as rows)",
]
