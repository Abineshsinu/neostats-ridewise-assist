# Policy Annexures — Transcribed from Embedded Images

This file is **derived data**. The three tables/figures below are embedded as
scanned images inside the source PDFs (plain text extraction misses them).
Each was extracted and visually read by the assistant; the source PDFs in
`data/raw/` were never modified. If a future policy image is added, re-run
`scripts/extract_images.py` and update this file by hand after visual review.

---

## Annexure 1 — Refund schedule (Version 2)

- **Source document:** `03_Cancellation_and_Refund_Policy_v2.pdf` (RW-POL-03, v2)
- **Page:** 2
- **Image:** embedded scanned image, page 2 (full-page scan with "APPROVED" stamp)
- **Applies to:** bookings with `booked_at` on or after **1 July 2026, 00:00 IST**
- **Approved by:** RideWise Policy Committee, 20 June 2026

| Cancellation before scheduled pickup | Refund of rental charge |
|---|---|
| 48 hours or more | 100% |
| 12 hours or more, but less than 48 hours | 75% |
| 2 hours or more, but less than 12 hours | 25% |
| Less than 2 hours | No refund (0%) |

- Cancelled by RideWise (CNL_S): 100% refund in all cases.
- No-show (NSH): no refund.

**Cross-check against brief's stated values:** matches exactly (48h→100%, 12h→75%, 2h→25%, <2h→0%). No discrepancy found.

---

## Annexure A — Tier benefits (late-return grace period)

- **Source document:** `04_Late_Return_and_Damage_Penalty_Schedule.pdf` (RW-POL-04, v2.1)
- **Page:** 3
- **Image:** embedded scanned image, page 3 (full-page scan with "APPROVED" stamp)
- **Approved by:** RideWise Policy Committee, 15 December 2024

| Customer tier | Grace period on late return |
|---|---|
| STANDARD | None |
| SILVER | None |
| GOLD | 30 minutes (up to and including 30 min) |

- A GOLD return up to **and including** 30 minutes late: no late fee.
- A GOLD return **more than** 30 minutes late: the **full lateness** is charged from the first minute, same as other tiers (no partial grace deduction).

**Cross-check against brief's stated values:** matches exactly (GOLD 30 min inclusive grace; over 30 min = full lateness charged, no grace deduction). No discrepancy found.

---

## Figure 2 — Battery level at return and the charging fee

- **Source document:** `05_EV_User_Guide_and_FAQ.pdf` (RW-POL-05, v1.4)
- **Page:** 2
- **Image:** embedded figure (battery-level bar chart), page 2

| Band | Range | Fee |
|---|---|---|
| RED | below 10% | ₹150 flat low-battery charging fee applies |
| AMBER | 10%–19% | No fee, but charge before next trip |
| GREEN | 20% and above | Ideal return level, no fee |

- Explicit note on the figure: "Exactly 10% is not below 10%, so no fee is charged."
- GST: per page 1 of the same document, "All penalties attract GST at 18%" — so the low-battery fee is ₹150 + 18% GST (₹27) = ₹177 total.
- Applies only to `EV_SCOOTER` and `EV_BIKE` vehicle types (non-EV vehicles have no `return_battery_pct`).
- A low-battery fee is independent of a late fee — FAQ on the same page: "No. They are separate. If the EV is both late and below 10%, both fees apply."

**Cross-check against brief's stated values:** matches exactly (below 10% → flat ₹150 + 18% GST = ₹27; exactly 10% → no fee). No discrepancy found.
