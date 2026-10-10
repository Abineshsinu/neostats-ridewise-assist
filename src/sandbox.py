"""
Per-session data isolation.

Customer session: an in-memory SQLite database containing ONLY that
customer's own rows (their customer row, their bookings, payments and
damage reports for those bookings, and the vehicles used in those
bookings). No other customer's data exists in that connection, so no SQL
— vetted tool or generated query — can ever reach it.

Agent session: an in-memory SQLite database containing ALL rows but with
PII masked at copy time (phone/licence to last 4, email masked, date of
birth dropped, free text redacted of email/phone-like patterns).

Both are built fresh from the real, read-only ridewise.db via ATTACH, so
the source file is never opened for writing and never mutated.
"""
from __future__ import annotations

import sqlite3

from src.db import DB_PATH
from src import masking
from src.city import normalize_city

SCHEMA = """
CREATE TABLE customers (
    customer_id        TEXT PRIMARY KEY,
    full_name          TEXT,
    phone              TEXT,
    email               TEXT,
    city                TEXT,
    date_of_birth       TEXT,
    driving_license_no  TEXT,
    kyc_status          TEXT,
    customer_tier       TEXT,
    created_at          TEXT
);
CREATE TABLE vehicles (
    vehicle_id           TEXT PRIMARY KEY,
    registration_no      TEXT,
    vehicle_type         TEXT,
    model                TEXT,
    hub_name             TEXT,
    hourly_rate          REAL,
    daily_rate           REAL,
    battery_capacity_kwh REAL,
    status               TEXT,
    commissioned_on      TEXT
);
CREATE TABLE bookings (
    booking_id         TEXT PRIMARY KEY,
    customer_id        TEXT,
    vehicle_id         TEXT,
    booked_at          TEXT,
    scheduled_start    TEXT,
    scheduled_end      TEXT,
    actual_return_at   TEXT,
    cancelled_at       TEXT,
    booking_status     TEXT,
    return_battery_pct INTEGER
);
CREATE TABLE payments (
    payment_id      TEXT PRIMARY KEY,
    booking_id      TEXT,
    payment_type    TEXT,
    amount          REAL,
    gst_amount      REAL,
    payment_method  TEXT,
    payment_status  TEXT,
    transaction_ref TEXT,
    paid_at         TEXT,
    remarks         TEXT
);
CREATE TABLE damage_reports (
    report_id       TEXT PRIMARY KEY,
    booking_id      TEXT,
    vehicle_id      TEXT,
    reported_by     TEXT,
    damage_category TEXT,
    severity        TEXT,
    description     TEXT,
    assessed_cost   REAL,
    claim_status    TEXT,
    reported_at     TEXT
);
"""


def _open_readonly_raw() -> sqlite3.Connection:
    uri = f"file:{DB_PATH.as_posix()}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    return con


def build_customer_sandbox(customer_id: str) -> sqlite3.Connection | None:
    """Return an in-memory connection scoped to exactly one customer's data,
    or None if the customer_id does not exist (caller gives a generic error,
    never revealing which case it was)."""
    raw = _open_readonly_raw()
    cur = raw.cursor()
    cur.execute("SELECT * FROM customers WHERE LOWER(customer_id) = LOWER(?)", (customer_id,))
    customer_row = cur.fetchone()
    if customer_row is None:
        raw.close()
        return None

    real_customer_id = customer_row["customer_id"]

    cur.execute("SELECT * FROM bookings WHERE customer_id = ?", (real_customer_id,))
    booking_rows = cur.fetchall()
    booking_ids = [b["booking_id"] for b in booking_rows]

    payment_rows = []
    damage_rows = []
    if booking_ids:
        placeholders = ",".join("?" for _ in booking_ids)
        cur.execute(f"SELECT * FROM payments WHERE booking_id IN ({placeholders})", booking_ids)
        payment_rows = cur.fetchall()
        cur.execute(f"SELECT * FROM damage_reports WHERE booking_id IN ({placeholders})", booking_ids)
        damage_rows = cur.fetchall()

    # The full vehicle catalog (model, type, hourly/daily rate) is published
    # rate-card information, not customer-private data — it's the same
    # table reproduced in RW-POL-04 Annexure/§1.5. Customers need it to ask
    # hypothetical questions ("what if I rent a Honda Activa and return
    # late?") about vehicles they haven't necessarily booked themselves.
    cur.execute("SELECT * FROM vehicles")
    vehicle_rows = cur.fetchall()

    raw.close()

    # check_same_thread=False: Streamlit can rerun the script in a new
    # thread per interaction while this connection lives in
    # st.session_state across reruns. Safe here because each in-memory
    # sandbox is private to one session and accessed by one request at a
    # time (no concurrent access from multiple threads simultaneously).
    sandbox = sqlite3.connect(":memory:", check_same_thread=False)
    sandbox.row_factory = sqlite3.Row
    sandbox.executescript(SCHEMA)

    _insert_rows(sandbox, "customers", [customer_row])
    _insert_rows(sandbox, "vehicles", vehicle_rows)
    _insert_rows(sandbox, "bookings", booking_rows)
    _insert_rows(sandbox, "payments", payment_rows)
    _insert_rows(sandbox, "damage_reports", damage_rows)
    sandbox.commit()
    return sandbox


def build_agent_connection() -> sqlite3.Connection:
    """Return an in-memory connection over ALL data, with PII masked at
    copy time: phone/licence to last 4, email masked, date of birth
    dropped, free text redacted of embedded emails/phone numbers."""
    raw = _open_readonly_raw()
    cur = raw.cursor()

    cur.execute("SELECT * FROM customers")
    customer_rows = [_normalize_customer_city(_mask_customer_row(r)) for r in cur.fetchall()]
    cur.execute("SELECT * FROM vehicles")
    vehicle_rows = cur.fetchall()
    cur.execute("SELECT * FROM bookings")
    booking_rows = cur.fetchall()
    cur.execute("SELECT * FROM payments")
    payment_rows = [_mask_payment_row(r) for r in cur.fetchall()]
    cur.execute("SELECT * FROM damage_reports")
    damage_rows = [_mask_damage_row(r) for r in cur.fetchall()]

    raw.close()

    agent_db = sqlite3.connect(":memory:", check_same_thread=False)
    agent_db.row_factory = sqlite3.Row
    agent_db.executescript(SCHEMA)

    _insert_rows(agent_db, "customers", customer_rows)
    _insert_rows(agent_db, "vehicles", vehicle_rows)
    _insert_rows(agent_db, "bookings", booking_rows)
    _insert_rows(agent_db, "payments", payment_rows)
    _insert_rows(agent_db, "damage_reports", damage_rows)
    agent_db.commit()
    return agent_db


def _normalize_customer_city(d: dict) -> dict:
    """customers.city is dirty in the source data (Bengaluru/Bangalore/BLR/
    "bangalore " all mean the same city). Normalized only for the agent
    connection, where it matters for grouping/filtering by city — never
    written back to ridewise.db."""
    d["city"] = normalize_city(d.get("city"))
    return d


def _mask_customer_row(r: sqlite3.Row) -> dict:
    d = dict(r)
    d["phone"] = masking.mask_phone(d.get("phone"))
    d["email"] = masking.mask_email(d.get("email"))
    d["driving_license_no"] = masking.mask_licence(d.get("driving_license_no"))
    d["date_of_birth"] = None
    return d


def _mask_payment_row(r: sqlite3.Row) -> dict:
    d = dict(r)
    d["remarks"] = masking.mask_free_text(d.get("remarks"))
    return d


def _mask_damage_row(r: sqlite3.Row) -> dict:
    d = dict(r)
    d["description"] = masking.mask_free_text(d.get("description"))
    return d


def _insert_rows(con: sqlite3.Connection, table: str, rows) -> None:
    if not rows:
        return
    first = dict(rows[0]) if not isinstance(rows[0], dict) else rows[0]
    columns = list(first.keys())
    placeholders = ",".join("?" for _ in columns)
    sql = f"INSERT INTO {table} ({','.join(columns)}) VALUES ({placeholders})"
    values = [tuple((dict(r) if not isinstance(r, dict) else r)[c] for c in columns) for r in rows]
    con.executemany(sql, values)
