"""Security tests: customer sandbox isolation and agent masking."""
import threading

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


def test_customer_sandbox_includes_full_vehicle_catalog():
    """The vehicle catalog (model/type/rates) is published rate-card info,
    not customer-private data — needed for hypothetical late-fee/battery-fee
    questions about models the customer hasn't actually rented."""
    con = build_customer_sandbox("CUST0001")
    cur = con.cursor()
    cur.execute("SELECT COUNT(*) AS c FROM vehicles")
    assert cur.fetchone()["c"] == 60
    cur.execute("SELECT 1 FROM vehicles WHERE model LIKE '%Activa%'")
    assert cur.fetchone() is not None


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


def test_agent_connection_normalizes_dirty_bengaluru_city_values():
    """Source data has city as 'Bengaluru' (79), 'Bangalore' (39), 'BLR'
    (29), and 'bangalore ' with a trailing space (17) — all the same city.
    Grouping by the normalized value on the agent connection must give a
    single 'Bengaluru' bucket of 164."""
    con = build_agent_connection()
    cur = con.cursor()
    cur.execute("SELECT city, COUNT(*) AS c FROM customers GROUP BY city ORDER BY c DESC")
    counts = {r["city"]: r["c"] for r in cur.fetchall()}
    assert counts.get("Bengaluru") == 164
    assert "Bangalore" not in counts
    assert "BLR" not in counts
    assert "bangalore " not in counts


# ---------------------------------------------------------------------------
# Regression: Streamlit reruns the script in a new thread per interaction,
# but the sandbox/agent connection lives in st.session_state across reruns.
# sqlite3 refuses cross-thread use by default ("SQLite objects created in a
# thread can only be used in that same thread"), which crashed every real
# query. Fixed with check_same_thread=False; these tests pin that down.
# ---------------------------------------------------------------------------

def test_customer_sandbox_usable_from_a_different_thread():
    con = build_customer_sandbox("CUST0012")
    assert con is not None

    outcome: dict = {}

    def worker():
        try:
            cur = con.cursor()
            cur.execute("SELECT booking_id FROM bookings")
            outcome["booking_ids"] = {r["booking_id"] for r in cur.fetchall()}
        except Exception as e:  # pragma: no cover - failure path under test
            outcome["error"] = e

    t = threading.Thread(target=worker)
    t.start()
    t.join()

    assert "error" not in outcome, f"cross-thread access raised: {outcome.get('error')}"
    assert outcome["booking_ids"] == {"B-1594", "B-1737", "B-1598", "B-1582"}


def test_agent_connection_usable_from_a_different_thread():
    con = build_agent_connection()
    outcome: dict = {}

    def worker():
        try:
            cur = con.cursor()
            cur.execute("SELECT COUNT(*) AS c FROM customers")
            outcome["count"] = cur.fetchone()["c"]
        except Exception as e:  # pragma: no cover - failure path under test
            outcome["error"] = e

    t = threading.Thread(target=worker)
    t.start()
    t.join()

    assert "error" not in outcome, f"cross-thread access raised: {outcome.get('error')}"
    assert outcome["count"] == 200


def test_two_customer_sandboxes_are_distinct_connections_and_never_share_data():
    con_a = build_customer_sandbox("CUST0001")
    con_b = build_customer_sandbox("CUST0002")

    assert con_a is not con_b

    cur_a, cur_b = con_a.cursor(), con_b.cursor()
    cur_a.execute("SELECT customer_id FROM customers")
    cur_b.execute("SELECT customer_id FROM customers")
    ids_a = {r["customer_id"] for r in cur_a.fetchall()}
    ids_b = {r["customer_id"] for r in cur_b.fetchall()}

    assert ids_a == {"CUST0001"}
    assert ids_b == {"CUST0002"}
    assert ids_a.isdisjoint(ids_b)


def test_building_a_new_session_never_reuses_a_prior_sandbox_object():
    """Each session start (or 'New conversation' / role switch) must build
    a fresh connection, never reuse one left over from a previous session —
    this is what makes 'reset ALL state on role/customer change' true at
    the connection level, not just at the UI's visible history level."""
    first = build_customer_sandbox("CUST0001")
    second = build_customer_sandbox("CUST0001")
    assert first is not second
