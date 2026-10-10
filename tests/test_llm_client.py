"""LLM client resilience tests — the real network client is always mocked."""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from openai import APITimeoutError, RateLimitError

from src.llm_client import FALLBACK_MESSAGE, LLMClient


def make_client() -> LLMClient:
    client = LLMClient.__new__(LLMClient)
    client.base_url = "https://example.test"
    client.api_key = "test-key"
    client.model = "test-model"
    client._client = MagicMock()
    return client


def fake_response(content: str | None, tool_calls=None):
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    choice = SimpleNamespace(message=message)
    return SimpleNamespace(choices=[choice])


def test_successful_chat_returns_content():
    client = make_client()
    client._client.chat.completions.create.return_value = fake_response("hello")
    result = client.chat([{"role": "user", "content": "hi"}])
    assert result.ok
    assert result.content == "hello"


def test_not_configured_returns_fallback():
    client = LLMClient.__new__(LLMClient)
    client.base_url = None
    client.api_key = None
    client.model = None
    client._client = None
    result = client.chat([{"role": "user", "content": "hi"}])
    assert not result.ok
    assert result.content == FALLBACK_MESSAGE


def test_empty_content_retries_then_succeeds():
    client = make_client()
    client._client.chat.completions.create.side_effect = [
        fake_response(""),
        fake_response("recovered"),
    ]
    result = client.chat([{"role": "user", "content": "hi"}], max_calls=2)
    assert result.ok
    assert result.content == "recovered"
    assert client._client.chat.completions.create.call_count == 2


def test_empty_content_both_attempts_falls_back():
    client = make_client()
    client._client.chat.completions.create.return_value = fake_response("")
    result = client.chat([{"role": "user", "content": "hi"}], max_calls=2)
    assert not result.ok
    assert result.content == FALLBACK_MESSAGE


def test_timeout_retries_then_succeeds():
    client = make_client()
    client._client.chat.completions.create.side_effect = [
        APITimeoutError(request=MagicMock()),
        fake_response("ok after retry"),
    ]
    result = client.chat([{"role": "user", "content": "hi"}], max_calls=2)
    assert result.ok
    assert result.content == "ok after retry"


def test_rate_limit_exhausts_retries_falls_back():
    client = make_client()
    client._client.chat.completions.create.side_effect = RateLimitError(
        "rate limited", response=MagicMock(status_code=429), body=None
    )
    result = client.chat([{"role": "user", "content": "hi"}], max_calls=2)
    assert not result.ok
    assert result.content == FALLBACK_MESSAGE
    assert client._client.chat.completions.create.call_count == 2


def test_tool_calls_returned_without_content():
    client = make_client()
    tool_calls = [SimpleNamespace(id="call_1", function=SimpleNamespace(name="get_booking", arguments="{}"))]
    client._client.chat.completions.create.return_value = fake_response(None, tool_calls=tool_calls)
    result = client.chat([{"role": "user", "content": "hi"}], tools=[{"type": "function"}])
    assert result.ok
    assert result.raw_tool_calls == tool_calls
