"""Composer tests — the LLM client is always mocked, no network calls."""
from unittest.mock import MagicMock

from src.llm_client import LLMResult
from src.composer import compose


def test_compose_calls_llm_with_evidence_in_delimiters():
    client = MagicMock()
    client.chat.return_value = LLMResult(ok=True, content="Here is your answer.")

    result = compose(
        client,
        question="What refund would I get?",
        assumptions=["Assumed booking B-0001 (your most recent)"],
        evidence=[{"type": "calculation", "tool": "refund", "value": {"total": "250.00"}}],
    )

    assert result.ok
    assert result.content == "Here is your answer."
    sent_messages = client.chat.call_args[0][0]
    user_msg = sent_messages[-1]["content"]
    assert "<evidence>" in user_msg
    assert "</evidence>" in user_msg
    assert "B-0001" in user_msg
    assert "refund" in user_msg


def test_compose_includes_assumptions_block():
    client = MagicMock()
    client.chat.return_value = LLMResult(ok=True, content="answer")
    compose(client, "question", ["Assumed X"], [])
    sent_messages = client.chat.call_args[0][0]
    assert "Assumed X" in sent_messages[-1]["content"]


def test_compose_handles_no_assumptions():
    client = MagicMock()
    client.chat.return_value = LLMResult(ok=True, content="answer")
    compose(client, "question", [], [])
    sent_messages = client.chat.call_args[0][0]
    assert "(none stated)" in sent_messages[-1]["content"]


def test_compose_propagates_llm_failure():
    client = MagicMock()
    client.chat.return_value = LLMResult(ok=False, content="fallback message", error="timeout")
    result = compose(client, "question", [], [])
    assert not result.ok
    assert result.content == "fallback message"
