"""Security tests: customer sandbox isolation and agent masking."""
from src.sandbox import build_agent_connection, build_customer_sandbox


def test_unknown_customer_id_returns_none():
    assert build_customer_sandbox("CUST9999") is None


def test_customer_sandbox_is_case_insensitive():
    con = build_customer_sandbox("cust0001")
    assert con is not None
    cur = con.cursor()
    cur.execute("SELECT customer_id FROM customers")
    assert cur.fetchone()["customer_id"] == "CUST0001"


def test_customer_sandbox_contains_only_that_customer():
    con = build_customer_sandbox("CUST0001")
    cur = con.cursor()
    cur.execute("SELECT COUNT(*) AS c FROM customers")
    assert cur.fetchone()["c"] == 1
    cur.execute("SELECT customer_id FROM bookings")
    for row in cur.fetchall():
        assert row["customer_id"] == "CUST0001"


def test_customer_sandbox_payments_belong_only_to_their_bookings():
    con = build_customer_sandbox("CUST0001")
    cur = con.cursor()
    cur.execute("SELECT booking_id FROM bookings")
    own_bookings = {r["booking_id"] for r in cur.fetchall()}
    cur.execute("SELECT DISTINCT booking_id FROM payments")
    payment_bookings = {r["booking_id"] for r in cur.fetchall()}
    assert payment_bookings <= own_bookings


def test_customer_sandbox_has_no_other_customer_rows_at_all():
    con = build_customer_sandbox("CUST0002")
    cur = con.cursor()
    cur.execute("SELECT customer_id FROM customers")
    ids = {r["customer_id"] for r in cur.fetchall()}
    assert ids == {"CUST0002"}


def test_agent_connection_masks_phone_email_dob():
    con = build_agent_connection()
    cur = con.cursor()
    cur.execute("SELECT phone, email, date_of_birth, driving_license_no FROM customers LIMIT 20")
    rows = cur.fetchall()
    assert len(rows) > 0
    for r in rows:
        assert r["date_of_birth"] is None
        if r["phone"]:
            assert r["phone"][:-4].count("X") == len(r["phone"]) - 4
        if r["email"]:
            assert "***" in r["email"] or r["email"].startswith("*@")


def test_agent_connection_masks_free_text_pii():
    con = build_agent_connection()
    cur = con.cursor()
    cur.execute("SELECT remarks FROM payments WHERE remarks IS NOT NULL")
    import re
    email_re = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
    phone_re = re.compile(r"\b[6-9]\d{9}\b")
    for r in cur.fetchall():
        assert not email_re.search(r["remarks"] or "")
        assert not phone_re.search(r["remarks"] or "")


def test_agent_connection_has_all_customers():
    con = build_agent_connection()
    cur = con.cursor()
    cur.execute("SELECT COUNT(*) AS c FROM customers")
    assert cur.fetchone()["c"] == 200
