"""
RideWise Assist — Streamlit chat UI.

Session layer: role and customer_id are chosen ONCE at the start screen
and stored only in st.session_state (server-side); chat text can never
change them (see src/guard.py). Changing role or customer_id, or clicking
"New conversation", resets ALL state — history and resolved entities —
so nothing leaks across sessions or roles.

Deliberately NOT stored in session_state: the sandbox/agent SQLite
connection itself. Streamlit's ScriptRunner can execute different reruns
of the same session on different OS threads, and a long-lived connection
object surviving across those reruns is exactly what caused a real
"SQLite objects created in a thread can only be used in that same thread"
crash in production. Rather than depend on getting a threading flag right
in a framework we don't fully control, we rebuild the (sub-millisecond,
in-memory) connection fresh on every turn from session_state.role /
session_state.customer_id. This also means the connection is always
created and used within the same function call on the same thread,
by construction — there is no cross-thread path left to get wrong.

This file is UI/display only. Every message — typed or from a sample
question button — goes through the exact same src.orchestrator.run_turn
call, with role/customer_id read only from session_state.
"""
from __future__ import annotations

import re

import streamlit as st

from src.llm_client import LLMClient
from src.orchestrator import run_turn
from src.policy_search import PolicySearch
from src.sandbox import build_agent_connection, build_customer_sandbox

st.set_page_config(page_title="RideWise Assist", page_icon="🛵", layout="wide")

SAMPLE_QUESTIONS = {
    "customer": [
        "Show me my bookings",
        "What refund would I get if I cancel booking B-1653 now?",
        "Why was I charged extra on booking B-0554?",
        "What's the late fee for a Honda Activa 6G returned 35 minutes late if I'm GOLD tier?",
    ],
    "agent": [
        "Tell me about booking B-0412",
        "What does the damage report for booking B-1104 say?",
        "What are the payments and payment remarks for booking B-0043?",
    ],
}

# Cosmetic only: some LLM responses append full-width-bracket reference
# markers like "【B-1653, B-0001】" alongside the citations already spelled
# out in prose and in the Evidence panel. Stripped only at render time —
# the raw answer is still what's stored in history and in the Evidence
# panel's data, and no booking id/amount/citation inside normal brackets
# or prose is touched, only this specific full-width-bracket artifact.
_CITATION_ARTIFACT_RE = re.compile(r"【[^】]*】")


def _clean_for_display(text: str) -> str:
    return _CITATION_ARTIFACT_RE.sub("", text).strip()


@st.cache_resource
def get_llm_client() -> LLMClient:
    return LLMClient()


@st.cache_resource
def get_policy_search() -> PolicySearch:
    return PolicySearch()


def reset_conversation() -> None:
    st.session_state.history = []
    st.session_state.resolved_entities = {}
    st.session_state.messages = []


def reset_session() -> None:
    st.session_state.role = None
    st.session_state.customer_id = None
    reset_conversation()


def get_session_connection():
    """Build the sandbox/agent connection fresh, from session_state.role
    and session_state.customer_id only — never from anything stored across
    reruns, and never from chat text. Called once per turn."""
    if st.session_state.role == "customer":
        return build_customer_sandbox(st.session_state.customer_id)
    return build_agent_connection()


def start_screen() -> None:
    st.title("🛵 RideWise Assist")
    st.caption("Your read-only assistant for RideWise bookings, payments and policies.")

    role_choice = st.radio("I am a...", ["Customer", "Support agent"], horizontal=True)

    if role_choice == "Customer":
        customer_id = st.text_input("Your customer ID", placeholder="e.g. CUST0001")
        if st.button("Start", type="primary"):
            if not customer_id.strip():
                st.error("Please enter a customer ID.")
                return
            # Validate the id exists now; the connection itself is rebuilt
            # fresh on every turn, never persisted in session_state.
            if build_customer_sandbox(customer_id.strip()) is None:
                st.error("We couldn't start a session with that customer ID. Please check it and try again.")
                return
            st.session_state.role = "customer"
            st.session_state.customer_id = customer_id.strip().upper()
            reset_conversation()
            st.rerun()
    else:
        st.info("Support agent sessions see operational data across customers, with personal data masked by default.")
        if st.button("Start as Support Agent", type="primary"):
            st.session_state.role = "agent"
            st.session_state.customer_id = None
            reset_conversation()
            st.rerun()


def _sidebar(role: str) -> None:
    with st.sidebar:
        st.subheader("Session")
        with st.container(border=True):
            st.markdown(f"**Role:** {'Customer' if role == 'customer' else 'Support agent'}")
            if st.session_state.customer_id:
                st.markdown(f"**Customer ID:** `{st.session_state.customer_id}`")

        col1, col2 = st.columns(2)
        with col1:
            if st.button("New conversation", use_container_width=True):
                reset_conversation()
                st.rerun()
        with col2:
            if st.button("End session", use_container_width=True):
                reset_session()
                st.rerun()

        st.divider()
        st.subheader("What you can ask")
        for q in SAMPLE_QUESTIONS[role]:
            st.markdown(f"- {q}")


def _welcome_message(role: str) -> str:
    if role == "customer":
        return (
            f"Hi! I'm RideWise Assist. Ask me about your bookings, payments, charges or our policies — "
            f"I'm read-only, so I can inform and estimate but I can't cancel, refund or edit anything."
        )
    return (
        "Hi! I'm RideWise Assist in support-agent mode. Ask about a specific booking, payment or damage "
        "report — personal data is masked by default, and I'm read-only."
    )


def _sample_question_buttons(role: str) -> str | None:
    cols = st.columns(len(SAMPLE_QUESTIONS[role]))
    clicked = None
    for col, q in zip(cols, SAMPLE_QUESTIONS[role]):
        with col:
            if st.button(q, use_container_width=True, key=f"sample_{q}"):
                clicked = q
    return clicked


def chat_screen() -> None:
    role = st.session_state.role
    _sidebar(role)

    st.title("🛵 RideWise Assist")

    if not st.session_state.messages:
        st.chat_message("assistant").markdown(_welcome_message(role))
        st.caption("Or try one of these:")
        clicked = _sample_question_buttons(role)
    else:
        clicked = None

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(_clean_for_display(msg["content"]))
            if msg.get("evidence"):
                with st.expander("Evidence"):
                    _render_evidence(msg["evidence"])

    user_input = clicked or st.chat_input("Ask about a booking, a charge, or a policy...")
    if user_input:
        st.session_state.messages.append({"role": "user", "content": user_input})
        with st.chat_message("user"):
            st.markdown(user_input)

        with st.chat_message("assistant"):
            with st.spinner("Checking your records..."):
                try:
                    con = get_session_connection()
                    result = run_turn(
                        get_llm_client(),
                        get_policy_search(),
                        con,
                        role,
                        user_input,
                        st.session_state.history,
                        st.session_state.resolved_entities,
                        customer_id=st.session_state.customer_id,
                    )
                except Exception:
                    st.error("Something went wrong while handling that. Please try again.")
                    st.session_state.messages.pop()  # drop the unanswered user turn
                    return
            st.markdown(_clean_for_display(result.answer))
            if result.evidence:
                with st.expander("Evidence"):
                    _render_evidence(result.evidence)

        st.session_state.history.append({"role": "user", "content": user_input})
        st.session_state.history.append({"role": "assistant", "content": result.answer})
        st.session_state.messages.append({"role": "assistant", "content": result.answer, "evidence": result.evidence})
        if clicked:
            st.rerun()


def _render_evidence(evidence: list[dict]) -> None:
    data_rows: dict[str, list[str]] = {}
    calculations = []
    policies = []

    for item in evidence:
        item_type = item.get("type")
        if item_type == "data" and "table" in item:
            data_rows.setdefault(item["table"], []).extend(item.get("row_ids", []))
        elif item_type == "calculation":
            calculations.append(item)
        elif item_type == "policy":
            policies.append(item)

    if data_rows:
        st.markdown("**Records used**")
        for table, ids in data_rows.items():
            ids = [i for i in ids if i]
            chips = " ".join(f"`{i}`" for i in ids) if ids else "_(none)_"
            st.markdown(f"- **{table}**: {chips}")

    if calculations:
        st.markdown("**Calculations**")
        for calc in calculations:
            st.markdown(f"_{calc.get('tool')}_")
            for i, step in enumerate(calc.get("steps", []), start=1):
                st.markdown(f"{i}. {step}")
            for cite in calc.get("citations", []):
                st.caption(f"Source: {cite.get('doc_id')} — {cite.get('title')} ({cite.get('section')})")

    if policies:
        st.markdown("**Policy references**")
        for p in policies:
            st.markdown(f"- **{p.get('doc_id')}** §{p.get('section')} — {p.get('title')}")
            if p.get("scope"):
                st.caption(p["scope"])

    with st.expander("Raw evidence (JSON)"):
        st.json(evidence)


def main() -> None:
    if "role" not in st.session_state:
        reset_session()

    if st.session_state.role is None:
        start_screen()
    else:
        chat_screen()


if __name__ == "__main__":
    main()
