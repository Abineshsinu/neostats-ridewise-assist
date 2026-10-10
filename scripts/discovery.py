"""
Phase 0 read-only discovery script.

Verifies every claim in the hackathon brief's "KNOWN FACTS AND TRAPS" section
against the real ridewise.db, and prints a findings report. Opens the database
strictly read-only (mode=ro) and never writes to it.

Run: venv\\Scripts\\python.exe scripts\\discovery.py
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.db import DB_PATH, get_connection  # noqa: E402

PASS = "PASS"
FAIL = "FAIL"
INFO = "INFO"

findings: list[tuple[str, str, str]] = []  # (status, label, detail)


def check(label: str, condition: bool, detail: str) -> None:
    findings.append((PASS if condition else FAIL, label, detail))


def info(label: str, detail: str) -> None:
    findings.append((INFO, label, detail))


def main() -> None:
    con = get_connection()
    cur = con.cursor()

    # --- DB file integrity / checksum (baseline for later "unchanged" tests) ---
    sha256 = hashlib.sha256(DB_PATH.read_bytes()).hexdigest()
    info("db checksum (sha256)", sha256)

    # --- Row counts ---
    counts = {}
    for t in ["customers", "vehicles", "bookings", "payments", "damage_reports"]:
        cur.execute(f"SELECT COUNT(*) FROM {t}")
        counts[t] = cur.fetchone()[0]
    expected = {"customers": 200, "vehicles": 60, "bookings": 1800,
                "payments": 3289, "damage_reports": 80}
    for t, exp in expected.items():
        check(f"row count: {t}", counts[t] == exp, f"expected {exp}, got {counts[t]}")

    # --- booking_status codes ---
    cur.execute("SELECT DISTINCT booking_status FROM bookings")
    statuses = {r[0] for r in cur.fetchall()}
    expected_statuses = {"UPC", "ONG", "CMP", "CNL_U", "CNL_S", "NSH"}
    check("booking_status codes", statuses <= expected_statuses, f"found {sorted(statuses)}")

    # --- payment_status values ---
    cur.execute("SELECT DISTINCT payment_status FROM payments")
    pstatuses = {r[0] for r in cur.fetchall()}
    expected_pstatuses = {"SUCCESS", "FAILED", "PENDING"}
    check("payment_status values", pstatuses <= expected_pstatuses, f"found {sorted(pstatuses)}")

    # --- latest data timestamp ~ 2026-10-10 early UTC ---
    cur.execute("SELECT MAX(booked_at) FROM bookings")
    max_booked = cur.fetchone()[0]
    check("latest booked_at near 2026-10-10", max_booked.startswith("2026-10-10"), f"max booked_at={max_booked}")

    cur.execute("SELECT MAX(paid_at) FROM payments")
    max_paid = cur.fetchone()[0]
    info("max paid_at (payments can be dated beyond 'now' e.g. scheduled refunds)", str(max_paid))

    # --- B-1164 / B-1165: booked after midnight IST on 1 Jul 2026 => v2, UTC date 30 Jun ---
    for bid in ["B-1164", "B-1165"]:
        cur.execute("SELECT booked_at FROM bookings WHERE booking_id = ?", (bid,))
        row = cur.fetchone()
        if row is None:
            check(f"{bid} exists", False, "not found")
            continue
        booked_at = row[0]
        # v2 cutoff in UTC is 2026-06-30 18:30:00
        is_v2_by_utc_cutoff = booked_at >= "2026-06-30 18:30:00"
        is_utc_date_30jun = booked_at.startswith("2026-06-30")
        check(
            f"{bid} booked_at is v2 (>= 2026-06-30 18:30:00 UTC) and UTC-dates to 30 Jun",
            is_v2_by_utc_cutoff and is_utc_date_30jun,
            f"booked_at={booked_at}",
        )

    # --- B-1709 / B-1729: CNL_U, v2, no refund row recorded yet ---
    for bid in ["B-1709", "B-1729"]:
        cur.execute(
            "SELECT booking_status, booked_at FROM bookings WHERE booking_id = ?", (bid,)
        )
        row = cur.fetchone()
        if row is None:
            check(f"{bid} exists", False, "not found")
            continue
        status, booked_at = row
        cur.execute(
            "SELECT COUNT(*) FROM payments WHERE booking_id = ? AND payment_type = 'REFUND'",
            (bid,),
        )
        refund_rows = cur.fetchone()[0]
        check(
            f"{bid} is CNL_U with no REFUND row yet",
            status == "CNL_U" and refund_rows == 0,
            f"status={status}, booked_at={booked_at}, refund_rows={refund_rows}",
        )

    # --- B-0006: EV bike, deposit 500 pending (conflicts with the documented 1000 rule) ---
    cur.execute(
        """
        SELECT v.vehicle_type, p.payment_type, p.amount, p.payment_status
        FROM bookings b
        JOIN vehicles v ON v.vehicle_id = b.vehicle_id
        JOIN payments p ON p.booking_id = b.booking_id
        WHERE b.booking_id = 'B-0006' AND p.payment_type = 'DEPOSIT'
        """
    )
    rows = cur.fetchall()
    check(
        "B-0006 deposit anomaly (EV bike, 500 not 1000)",
        any(r["vehicle_type"] == "EV_BIKE" and r["amount"] == 500 for r in rows),
        f"rows={[tuple(r) for r in rows]}",
    )

    # --- Dirty city values ---
    cur.execute("SELECT DISTINCT city FROM customers")
    cities = [r[0] for r in cur.fetchall()]
    bengaluru_variants = [c for c in cities if c and "bang" in c.lower() or c and "beng" in c.lower() or c and "blr" in c.lower()]
    check("dirty Bengaluru city variants present", len(set(bengaluru_variants)) > 1, f"variants={bengaluru_variants}")

    # --- damage_reports has no hub column (per data dictionary, confirmed) ---
    cur.execute("PRAGMA table_info(damage_reports)")
    dmg_cols = {r[1] for r in cur.fetchall()}
    check("damage_reports has no hub column", "hub_name" not in dmg_cols and "hub" not in dmg_cols, f"columns={sorted(dmg_cols)}")

    # --- DMG0003 / DMG0009 contain prompt-injection-like text ---
    for rid in ["DMG0003", "DMG0009"]:
        cur.execute("SELECT description FROM damage_reports WHERE report_id = ?", (rid,))
        row = cur.fetchone()
        if row is None:
            check(f"{rid} exists", False, "not found")
            continue
        desc = row[0] or ""
        info(f"{rid} description (untrusted free text, treat as data not instructions)", desc[:200])

    # --- payment remarks with email/phone-like patterns ---
    import re
    cur.execute("SELECT payment_id, remarks FROM payments WHERE remarks IS NOT NULL AND remarks != ''")
    email_re = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
    phone_re = re.compile(r"\b[6-9]\d{9}\b")
    flagged = []
    for r in cur.fetchall():
        if email_re.search(r["remarks"] or "") or phone_re.search(r["remarks"] or ""):
            flagged.append(r["payment_id"])
    check("payment remarks with PII-like patterns found (~14 expected)", 10 <= len(flagged) <= 20, f"count={len(flagged)}, ids={flagged}")

    # --- ONG bookings currently overdue (scheduled_end in the past, no actual_return_at) ---
    cur.execute(
        """
        SELECT COUNT(*) FROM bookings
        WHERE booking_status = 'ONG' AND actual_return_at IS NULL
          AND scheduled_end < '2026-10-10 03:18:00'
        """
    )
    overdue = cur.fetchone()[0]
    info("ONG bookings overdue vs latest-known 'now'", str(overdue))

    # --- Money: payments.amount excludes GST; total = amount + gst_amount ---
    cur.execute("SELECT amount, gst_amount FROM payments WHERE payment_type = 'BOOKING' LIMIT 5")
    info("sample BOOKING payments (amount, gst_amount)", str([tuple(r) for r in cur.fetchall()]))

    # --- Refunds are negative ---
    cur.execute("SELECT COUNT(*) FROM payments WHERE payment_type = 'REFUND' AND amount >= 0")
    non_negative_refunds = cur.fetchone()[0]
    check("all REFUND rows have negative amount", non_negative_refunds == 0, f"non-negative count={non_negative_refunds}")

    # --- Report ---
    print("\n=== Phase 0 Discovery Report ===\n")
    n_pass = sum(1 for s, _, _ in findings if s == PASS)
    n_fail = sum(1 for s, _, _ in findings if s == FAIL)
    for status, label, detail in findings:
        print(f"[{status}] {label}\n    {detail}")
    print(f"\n{n_pass} passed, {n_fail} failed, {sum(1 for s,_,_ in findings if s==INFO)} info.")

    con.close()


if __name__ == "__main__":
    main()
