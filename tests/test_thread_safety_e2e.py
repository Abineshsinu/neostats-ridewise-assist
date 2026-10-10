"""
End-to-end regression test for the Streamlit cross-thread crash:
"SQLite objects created in a thread can only be used in that same thread."

This goes through the exact path the app uses — build a connection, then
call src.orchestrator.run_turn with it from a *different* thread than the
one that built it (reproducing Streamlit's ScriptRunner, which can run
different reruns of the same session on different OS threads while
st.session_state keeps the same Python object alive across them).

The "before" test uses a raw sqlite3 connection with the Python default
(check_same_thread=True) to prove this exact crash is reproducible through
run_turn when the thread-safety flag is absent. The "after" test uses the
real src.sandbox connections (check_same_thread=False) and must succeed.
"""
import sqlite3
import threading
from unittest.mock import MagicMock

import pytest

from src.llm_client import LLMResult
from src.orchestrator import run_turn
from src.policy_search import PolicySearch
from src.sandbox import SCHEMA, build_agent_connection, build_customer_sandbox

_policy_search = None


def get_policy_search() -> PolicySearch:
    global _policy_search
    if _policy_search is None:
        _policy_search = PolicySearch()
    return _policy_search


def _mock_client_for_list_bookings() -> MagicMock:
    import json

    client = MagicMock()
    client.chat.return_value = LLMResult(
        ok=True,
        content=json.dumps({"intent": "list_bookings", "entities": {}, "needs": ["data"]}),
    )
    return client


def _run_turn_on_other_thread(con, role: str, message: str) -> dict:
    """Builds the request on a worker thread, exactly like a Streamlit
    rerun executing on a pooled thread different from the one that built
    the connection. Returns {'ok': True, 'result': ...} or {'ok': False,
    'error': Exception}."""
    outcome: dict = {}

    def worker():
        try:
            result = run_turn(_mock_client_for_list_bookings(), get_policy_search(), con, role, message, [], {})
            outcome["ok"] = True
            outcome["result"] = result
        except Exception as e:
            outcome["ok"] = False
            outcome["error"] = e

    t = threading.Thread(target=worker)
    t.start()
    t.join()
    return outcome


def test_before_fix_raw_connection_crashes_through_run_turn_on_another_thread():
    """Demonstrates the exact failure mode: a connection built with the
    Python sqlite3 default (check_same_thread=True) crashes with
    "SQLite objects created in a thread can only be used in that same
    thread" the moment run_turn (via the vetted tools) queries it from a
    different thread than the one that built it. This is "before" the fix
    — src.sandbox used to build connections this way."""
    unsafe_con = sqlite3.connect(":memory:")  # default check_same_thread=True
    unsafe_con.row_factory = sqlite3.Row
    unsafe_con.executescript(SCHEMA)
    unsafe_con.execute(
        "INSERT INTO customers (customer_id, full_name, customer_tier) VALUES ('CUST0001', 'Test', 'STANDARD')"
    )
    unsafe_con.execute(
        "INSERT INTO bookings (booking_id, customer_id, vehicle_id, booking_status, scheduled_start, scheduled_end) "
        "VALUES ('B-0001', 'CUST0001', 'VEH001', 'CMP', '2026-08-15 04:30:00', '2026-08-15 08:30:00')"
    )
    unsafe_con.commit()

    outcome = _run_turn_on_other_thread(unsafe_con, "customer", "show me my bookings")

    assert not outcome["ok"], "expected the unsafe connection to crash across threads, but it didn't"
    assert isinstance(outcome["error"], sqlite3.ProgrammingError)
    assert "only be used in that same thread" in str(outcome["error"])


def test_after_fix_real_customer_sandbox_works_through_run_turn_on_another_thread():
    """The actual path the app uses: build the real customer sandbox (which
    carries check_same_thread=False), then call run_turn with it from a
    different thread. Must succeed — this is "after" the fix."""
    con = build_customer_sandbox("CUST0001")
    assert con is not None

    outcome = _run_turn_on_other_thread(con, "customer", "show me my bookings")

    assert outcome["ok"], f"run_turn crashed across threads: {outcome.get('error')}"
    result = outcome["result"]
    assert any(e.get("type") == "data" for e in result.evidence)


def test_after_fix_agent_connection_works_through_run_turn_on_another_thread():
    con = build_agent_connection()
    outcome = _run_turn_on_other_thread(con, "agent", "show me my bookings")
    assert outcome["ok"], f"run_turn crashed across threads: {outcome.get('error')}"
