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
"""
from __future__ import annotations

import streamlit as st

from src.llm_client import LLMClient
from src.orchestrator import run_turn
from src.policy_search import PolicySearch
from src.sandbox import build_agent_connection, build_customer_sandbox

st.set_page_config(page_title="RideWise Assist", page_icon="🛵", layout="centered")


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
    st.caption("Read-only assistant for RideWise bookings, payments and policies.")

    role_choice = st.radio("I am a...", ["Customer", "Support agent"], horizontal=True)

    if role_choice == "Customer":
        customer_id = st.text_input("Your customer ID (e.g. CUST0001)")
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


def chat_screen() -> None:
    role = st.session_state.role
    with st.sidebar:
        st.markdown(f"**Role:** {'Customer' if role == 'customer' else 'Support agent'}")
        if st.session_state.customer_id:
            st.markdown(f"**Customer:** {st.session_state.customer_id}")
        st.divider()
        if st.button("New conversation"):
            reset_conversation()
            st.rerun()
        if st.button("End session"):
            reset_session()
            st.rerun()

    st.title("🛵 RideWise Assist")

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg.get("evidence"):
                with st.expander("Evidence"):
                    _render_evidence(msg["evidence"])

    user_input = st.chat_input("Ask about a booking, a charge, or a policy...")
    if user_input:
        st.session_state.messages.append({"role": "user", "content": user_input})
        with st.chat_message("user"):
            st.markdown(user_input)

        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                con = get_session_connection()
                result = run_turn(
                    get_llm_client(),
                    get_policy_search(),
                    con,
                    role,
                    user_input,
                    st.session_state.history,
                    st.session_state.resolved_entities,
                )
            st.markdown(result.answer)
            if result.evidence:
                with st.expander("Evidence"):
                    _render_evidence(result.evidence)

        st.session_state.history.append({"role": "user", "content": user_input})
        st.session_state.history.append({"role": "assistant", "content": result.answer})
        st.session_state.messages.append({"role": "assistant", "content": result.answer, "evidence": result.evidence})


def _render_evidence(evidence: list[dict]) -> None:
    for item in evidence:
        item_type = item.get("type")
        if item_type == "data":
            if "table" in item:
                st.markdown(f"**Data:** `{item['table']}` rows: {', '.join(item.get('row_ids', [])) or '(none)'}")
            else:
                st.json(item.get("payload"))
        elif item_type == "calculation":
            st.markdown(f"**Calculation:** `{item.get('tool')}`")
            for step in item.get("steps", []):
                st.markdown(f"- {step}")
            for cite in item.get("citations", []):
                st.caption(f"Source: {cite.get('doc_id')} — {cite.get('title')} ({cite.get('section')})")
        elif item_type == "policy":
            st.markdown(f"**Policy:** {item.get('doc_id')} §{item.get('section')} — {item.get('title')}")
            st.caption(item.get("scope", ""))
            st.text(item.get("text", "")[:500])


def main() -> None:
    if "role" not in st.session_state:
        reset_session()

    if st.session_state.role is None:
        start_screen()
    else:
        chat_screen()


if __name__ == "__main__":
    main()
