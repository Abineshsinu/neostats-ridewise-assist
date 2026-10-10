"""Audit log tests. Always redirect LOG_FILE to a temp path — never touch
the real git-ignored logs/ folder from the test suite."""
import json

from src import audit


def test_log_event_writes_one_jsonl_line(tmp_path, monkeypatch):
    log_file = tmp_path / "audit.jsonl"
    monkeypatch.setattr(audit, "LOG_DIR", tmp_path)
    monkeypatch.setattr(audit, "LOG_FILE", log_file)

    audit.log_event("customer", "CUST0001", tool="booking_detail", row_count=1)

    lines = log_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["role"] == "customer"
    assert entry["customer_id"] == "CUST0001"
    assert entry["tool"] == "booking_detail"
    assert entry["row_count"] == 1
    assert "timestamp" in entry


def test_agent_events_always_log_customer_id_as_agent(tmp_path, monkeypatch):
    log_file = tmp_path / "audit.jsonl"
    monkeypatch.setattr(audit, "LOG_DIR", tmp_path)
    monkeypatch.setattr(audit, "LOG_FILE", log_file)

    audit.log_event("agent", None, tool="payments_for_booking", masking_applied=True)

    entry = json.loads(log_file.read_text(encoding="utf-8").strip())
    assert entry["customer_id"] == "agent"
    assert entry["masking_applied"] is True


def test_refusal_event_logged_with_reason(tmp_path, monkeypatch):
    log_file = tmp_path / "audit.jsonl"
    monkeypatch.setattr(audit, "LOG_DIR", tmp_path)
    monkeypatch.setattr(audit, "LOG_FILE", log_file)

    audit.log_event("customer", "CUST0001", refusal_reason="secret_request")

    entry = json.loads(log_file.read_text(encoding="utf-8").strip())
    assert entry["refusal_reason"] == "secret_request"
    assert entry["tool"] is None


def test_multiple_events_append_as_separate_lines(tmp_path, monkeypatch):
    log_file = tmp_path / "audit.jsonl"
    monkeypatch.setattr(audit, "LOG_DIR", tmp_path)
    monkeypatch.setattr(audit, "LOG_FILE", log_file)

    audit.log_event("customer", "CUST0001", tool="booking_detail")
    audit.log_event("customer", "CUST0001", tool="refund_estimate")

    lines = log_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2


def test_log_event_never_raises_even_if_write_fails(monkeypatch):
    def broken_mkdir(*a, **kw):
        raise OSError("disk full")

    monkeypatch.setattr(type(audit.LOG_DIR), "mkdir", broken_mkdir)
    audit.log_event("customer", "CUST0001", tool="booking_detail")  # must not raise


def test_log_event_contains_no_message_text_field():
    """Structural guarantee: log_event's signature has no parameter for raw
    user message text, so it's impossible to accidentally log it."""
    import inspect

    params = inspect.signature(audit.log_event).parameters
    assert "user_message" not in params
    assert "message" not in params
    assert "text" not in params
