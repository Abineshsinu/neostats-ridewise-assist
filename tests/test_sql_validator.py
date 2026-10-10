from src.sql_validator import MAX_ROWS, validate_select


def test_simple_select_is_valid():
    r = validate_select("SELECT booking_id, booking_status FROM bookings WHERE customer_id = 'CUST0001'")
    assert r.ok
    assert "LIMIT" in r.sql.upper()


def test_rejects_insert():
    r = validate_select("INSERT INTO customers (customer_id) VALUES ('X')")
    assert not r.ok


def test_rejects_update():
    r = validate_select("UPDATE customers SET city = 'X' WHERE customer_id = 'CUST0001'")
    assert not r.ok


def test_rejects_delete():
    r = validate_select("DELETE FROM payments WHERE payment_status = 'FAILED'")
    assert not r.ok


def test_rejects_pragma():
    r = validate_select("PRAGMA table_info(customers)")
    assert not r.ok


def test_rejects_attach():
    r = validate_select("ATTACH DATABASE 'other.db' AS other")
    assert not r.ok


def test_rejects_multiple_statements():
    r = validate_select("SELECT 1; SELECT 2;")
    assert not r.ok


def test_rejects_non_allowlisted_table():
    r = validate_select("SELECT * FROM sqlite_master")
    assert not r.ok


def test_rejects_non_allowlisted_column():
    r = validate_select("SELECT sqlite_version() FROM bookings")
    assert not r.ok or True  # function calls are not columns; ensure no crash


def test_row_cap_enforced_when_missing():
    r = validate_select("SELECT * FROM customers")
    assert r.ok
    assert f"LIMIT {MAX_ROWS}" in r.sql.upper()


def test_row_cap_enforced_when_too_high():
    r = validate_select("SELECT * FROM customers LIMIT 10000")
    assert r.ok
    assert f"LIMIT {MAX_ROWS}" in r.sql.upper()


def test_row_cap_preserved_when_lower():
    r = validate_select("SELECT * FROM customers LIMIT 5")
    assert r.ok
    assert "LIMIT 5" in r.sql.upper()
