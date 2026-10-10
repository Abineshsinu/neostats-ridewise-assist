"""Planner tests — the LLM client is always mocked, no network calls."""
import json
from unittest.mock import MagicMock

from src.llm_client import LLMResult
from src.planner import FALLBACK_PLAN, plan


def mock_client(*contents: str) -> MagicMock:
    client = MagicMock()
    results = [LLMResult(ok=True, content=c) for c in contents]
    client.chat.side_effect = results
    return client


def test_valid_json_parses_into_plan():
    content = json.dumps({
        "intent": "refund_estimate",
        "entities": {"booking_id": "B-0001", "hypothetical": True},
        "needs": ["data", "calculation", "policy"],
    })
    client = mock_client(content)
    result = plan(client, "What refund would I get if I cancel booking B-0001 now?")
    assert result.intent == "refund_estimate"
    assert result.entities.booking_id == "B-0001"
    assert result.entities.hypothetical is True
    assert set(result.needs) == {"data", "calculation", "policy"}


def test_json_wrapped_in_prose_is_extracted():
    content = 'Sure, here is the plan:\n{"intent": "policy_question", "entities": {}, "needs": ["policy"]}\nHope that helps.'
    client = mock_client(content)
    result = plan(client, "What is the cancellation policy?")
    assert result.intent == "policy_question"


def test_invalid_json_retries_once_then_succeeds():
    client = mock_client("not json at all", json.dumps({"intent": "data_lookup", "entities": {}, "needs": ["data"]}))
    result = plan(client, "show me my bookings")
    assert result.intent == "data_lookup"
    assert client.chat.call_count == 2


def test_invalid_json_both_attempts_falls_back_to_clarification():
    client = mock_client("garbage", "still garbage")
    result = plan(client, "???")
    assert result == FALLBACK_PLAN
    assert result.clarification_question is not None


def test_llm_failure_falls_back_to_clarification():
    client = MagicMock()
    client.chat.return_value = LLMResult(ok=False, content="fallback message", error="timeout")
    result = plan(client, "hello")
    assert result == FALLBACK_PLAN


def test_late_fee_hypothetical_entities_parse():
    content = json.dumps({
        "intent": "late_fee_hypothetical",
        "entities": {"vehicle_type": "SCOOTER", "tier": "GOLD", "delay_minutes": 35, "hypothetical": True},
        "needs": ["calculation", "policy"],
    })
    client = mock_client(content)
    result = plan(client, "What's the late fee for a scooter returned 35 minutes late on GOLD tier?")
    assert result.intent == "late_fee_hypothetical"
    assert result.entities.delay_minutes == 35
    assert result.entities.tier == "GOLD"


def test_battery_fee_hypothetical_entities_parse():
    content = json.dumps({
        "intent": "battery_fee_hypothetical",
        "entities": {"vehicle_type": "EV_SCOOTER", "battery_pct": 7},
        "needs": ["calculation", "policy"],
    })
    client = mock_client(content)
    result = plan(client, "What if an EV scooter comes back at 7% battery?")
    assert result.intent == "battery_fee_hypothetical"
    assert result.entities.battery_pct == 7


def test_out_of_scope_intent():
    content = json.dumps({"intent": "out_of_scope", "entities": {}, "needs": ["out_of_scope"]})
    client = mock_client(content)
    result = plan(client, "what's the weather today?")
    assert result.needs == ["out_of_scope"]
