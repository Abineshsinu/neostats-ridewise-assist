"""
Minimal follow-up memory test, per the brief's exact scenario: late fee
for a scooter, then "and for an EV?", then "what if I'm Gold?". Memory is
maintained by code (src/orchestrator.py), not the LLM — these tests use a
planner mock that deliberately omits any entity the user didn't restate,
simulating a real model that relies on conversation memory rather than
re-stating everything every turn. If the code's memory handling were
missing, these would fail with a vehicle-not-found clarification instead
of a computed fee.
"""
import json
from decimal import Decimal
from unittest.mock import MagicMock

from src.llm_client import LLMResult
from src.orchestrator import run_turn
from src.policy_search import PolicySearch
from src.sandbox import build_customer_sandbox

_policy_search = None


def get_policy_search() -> PolicySearch:
    global _policy_search
    if _policy_search is None:
        _policy_search = PolicySearch()
    return _policy_search


def mock_turn(plan_dict: dict, answer: str) -> MagicMock:
    client = MagicMock()
    client.chat.side_effect = [
        LLMResult(ok=True, content=json.dumps(plan_dict)),
        LLMResult(ok=True, content=answer),
    ]
    return client


def test_late_fee_scooter_then_ev_then_gold_tier_sequence():
    con = build_customer_sandbox("CUST0001")
    history: list[dict] = []
    resolved_entities: dict = {}

    # Turn 1: full statement — scooter model, 40 min late, STANDARD (implicit).
    client1 = mock_turn(
        {"intent": "late_fee_hypothetical", "entities": {"vehicle_model": "Honda Activa 6G", "delay_minutes": 40}, "needs": ["calculation", "policy"]},
        "late fee answer 1",
    )
    result1 = run_turn(client1, get_policy_search(), con, "customer", "Late fee for a Honda Activa 6G returned 40 minutes late?", history, resolved_entities)
    assert resolved_entities["vehicle_model"] == "Honda Activa 6G"
    assert resolved_entities["delay_minutes"] == 40
    r1_fee = _fee_from_evidence(result1.evidence)
    assert r1_fee == Decimal("90.00")  # 1hr x 1.5 x 60 (Activa rate), STANDARD no grace
    history += [{"role": "user", "content": "..."}, {"role": "assistant", "content": result1.answer}]

    # Turn 2: "and for an EV?" — planner (simulated) omits delay_minutes and
    # tier entirely, relying on memory; only states the new vehicle_type.
    client2 = mock_turn(
        {"intent": "late_fee_hypothetical", "entities": {"vehicle_type": "EV_SCOOTER"}, "needs": ["calculation", "policy"]},
        "late fee answer 2",
    )
    result2 = run_turn(client2, get_policy_search(), con, "customer", "and for an EV?", history, resolved_entities)
    assert resolved_entities["vehicle_type"] == "EV_SCOOTER"
    assert resolved_entities["vehicle_model"] is None  # stale "Activa" model correctly dropped
    assert resolved_entities["delay_minutes"] == 40  # delay still remembered
    r2_items = [r for r in result2.evidence if r.get("type") == "data"][0]["payload"]["results"]
    assert all(r["vehicle_type"] == "EV_SCOOTER" for r in r2_items)
    assert all(r["delay_minutes"] == 40 for r in r2_items)
    history += [{"role": "user", "content": "..."}, {"role": "assistant", "content": result2.answer}]

    # Turn 3: "what if I'm Gold?" — planner omits vehicle entirely, only
    # states the tier change.
    client3 = mock_turn(
        {"intent": "late_fee_hypothetical", "entities": {"tier": "GOLD"}, "needs": ["calculation", "policy"]},
        "late fee answer 3",
    )
    result3 = run_turn(client3, get_policy_search(), con, "customer", "what if I'm Gold?", history, resolved_entities)
    assert resolved_entities["tier"] == "GOLD"
    assert resolved_entities["vehicle_type"] == "EV_SCOOTER"  # still remembered from turn 2
    r3_items = [r for r in result3.evidence if r.get("type") == "data"][0]["payload"]["results"]
    assert all(r["vehicle_type"] == "EV_SCOOTER" for r in r3_items)
    assert all(r["tier"] == "GOLD" for r in r3_items)
    # 40 min > 30 min GOLD grace -> full lateness charged (1hr), not reduced.
    r3_fee = _fee_from_evidence(result3.evidence)
    assert r3_fee is not None


def _fee_from_evidence(evidence: list[dict]) -> Decimal | None:
    for item in evidence:
        if item.get("type") == "data" and "payload" in item and "results" in item.get("payload", {}):
            results = item["payload"]["results"]
            if results:
                return Decimal(results[0]["result"]["fee"])
    return None
