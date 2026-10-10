"""
Wires one turn together: guard -> plan -> vetted tools / policy search ->
compose. This is the only place that decides which tool to call; the
customer_id and role it operates on come from the Session object the
caller passes in, never from chat text or from the planner's output.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from src import audit
from src import data_access as da
from src import guard
from src.composer import compose
from src.llm_client import LLMClient
from src.output_check import run_output_check
from src.planner import Plan, plan
from src.policy_search import PolicySearch

VERSION_TO_DOC = {"v1": "RW-POL-02", "v2": "RW-POL-03"}


@dataclass
class TurnResult:
    answer: str
    evidence: list[dict] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    plan: Plan | None = None


def run_turn(
    client: LLMClient,
    policy_search: PolicySearch,
    con: sqlite3.Connection,
    role: str,
    user_message: str,
    history: list[dict],
    resolved_entities: dict,
    customer_id: str | None = None,
) -> TurnResult:
    guard_result = guard.check_input(user_message)
    if not guard_result.allowed:
        audit.log_event(role, customer_id, refusal_reason=guard_result.reason)
        return TurnResult(answer=guard_result.refusal_message, evidence=[], assumptions=[])

    the_plan = plan(client, user_message, history, resolved_entities)

    if "out_of_scope" in the_plan.needs or the_plan.intent == "out_of_scope":
        audit.log_event(role, customer_id, refusal_reason="out_of_scope")
        return TurnResult(answer=guard.SCOPED_REFUSAL, evidence=[], assumptions=[], plan=the_plan)

    if the_plan.intent == "clarify" and the_plan.clarification_question:
        return TurnResult(answer=the_plan.clarification_question, evidence=[], assumptions=[], plan=the_plan)

    # Merge newly resolved entities into the running memory (code-managed, not the LLM's job).
    for key, value in the_plan.entities.model_dump().items():
        if value not in (None, False):
            resolved_entities[key] = value

    evidence: list[dict] = []
    assumptions: list[str] = []
    booking_id = the_plan.entities.booking_id or resolved_entities.get("booking_id")

    if "data" in the_plan.needs or "calculation" in the_plan.needs:
        if role == "customer":
            # The connection is already scoped to this customer's own data
            # (fixed by the session, never by chat text — see src/guard.py).
            # Tell the composer explicitly so it doesn't go looking for a
            # customer_id column to "confirm" whose data this is.
            assumptions.append(
                "All data evidence below belongs to the customer's own account for this session "
                "(scoped by the session, not by any customer ID mentioned in chat text). "
                "There is no customer_id column to match against."
            )
        tool_evidence, tool_assumptions, early_refusal = _run_data_tools(con, role, the_plan, booking_id)
        evidence.extend(tool_evidence)
        assumptions.extend(tool_assumptions)
        if early_refusal:
            audit.log_event(role, customer_id, tool=the_plan.intent, refusal_reason="not_found")
            return TurnResult(answer=early_refusal, evidence=evidence, assumptions=assumptions, plan=the_plan)
        elif tool_evidence:
            audit.log_event(role, customer_id, tool=the_plan.intent, row_count=len(tool_evidence), masking_applied=(role == "agent"))

    if "policy" in the_plan.needs:
        applicable_doc = None
        version = resolved_entities.get("_policy_version")
        if version:
            applicable_doc = VERSION_TO_DOC.get(version)
        results = policy_search.search_for_version(user_message, applicable_doc, top_k=5)
        for chunk, score in results:
            evidence.append({
                "type": "policy",
                "doc_id": chunk.doc_id,
                "title": chunk.title,
                "section": chunk.section,
                "scope": chunk.scope,
                "text": chunk.text,
            })

    if not evidence:
        return TurnResult(
            answer="I don't have evidence to answer that from your account or our policies — could you tell me a bit more, like a booking ID?",
            evidence=[],
            assumptions=assumptions,
            plan=the_plan,
        )

    result = compose(client, user_message, assumptions, evidence)
    checked_answer, warnings = run_output_check(result.content, role, evidence)
    if warnings:
        checked_answer = checked_answer + "\n\n" + "\n".join(warnings)
    return TurnResult(answer=checked_answer, evidence=evidence, assumptions=assumptions, plan=the_plan)


def _run_data_tools(con, role: str, the_plan: Plan, booking_id: str | None) -> tuple[list[dict], list[str], str | None]:
    evidence: list[dict] = []
    assumptions: list[str] = []

    if the_plan.intent in ("booking_lookup", "list_bookings") and not booking_id:
        result = da.list_my_bookings(con)
        if result.ok:
            evidence.extend(result.evidence)
            evidence.append({"type": "data", "payload": result.data})
        return evidence, assumptions, None

    if not booking_id:
        return evidence, assumptions, None

    if the_plan.intent in ("refund_estimate",) or the_plan.entities.hypothetical:
        result = da.refund_estimate(con, booking_id)
    elif the_plan.intent in ("charge_explain", "explain_charge"):
        result = da.explain_charge(con, booking_id)
    elif the_plan.intent in ("payments_lookup",):
        result = da.payments_for_booking(con, booking_id)
    else:
        result = da.booking_detail(con, booking_id)

    if not result.ok:
        return evidence, assumptions, result.message

    evidence.extend(result.evidence)
    evidence.append({"type": "data", "payload": result.data})
    if result.message:
        assumptions.append(result.message)
    return evidence, assumptions, None
