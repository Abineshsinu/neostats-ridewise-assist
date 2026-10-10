"""
Phase 0: probe the NeoStats-hosted LLM endpoint.

Checks: basic chat completion, latency, whether it honors JSON-mode style
instructions, whether it supports OpenAI-style tool calling, whether it
returns separate "reasoning" fields (gpt-oss style), and whether an
embeddings endpoint is available. Never prints the API key.
"""
from __future__ import annotations

import os
import time

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

BASE_URL = os.environ["LLM_BASE_URL"]
API_KEY = os.environ["LLM_API_KEY"]
MODEL = os.environ["LLM_MODEL"]

client = OpenAI(base_url=BASE_URL, api_key=API_KEY)


def test_basic_chat() -> None:
    print("\n--- basic chat completion ---")
    t0 = time.time()
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": "Reply with exactly one word: pong"}],
    )
    dt = time.time() - t0
    msg = resp.choices[0].message
    print(f"latency: {dt:.2f}s")
    print(f"content: {msg.content!r}")
    print(f"has reasoning field: {hasattr(msg, 'reasoning') and msg.reasoning is not None}")
    if hasattr(msg, "reasoning"):
        print(f"reasoning (truncated): {str(msg.reasoning)[:200]!r}")
    print(f"finish_reason: {resp.choices[0].finish_reason}")
    print(f"usage: {resp.usage}")


def test_json_mode() -> None:
    print("\n--- JSON output instruction-following ---")
    t0 = time.time()
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": "You respond ONLY with valid JSON, no prose, no markdown fences."},
            {"role": "user", "content": 'Return {"intent": "test", "ok": true}'},
        ],
    )
    dt = time.time() - t0
    content = resp.choices[0].message.content
    print(f"latency: {dt:.2f}s")
    print(f"content: {content!r}")
    try:
        import json
        json.loads(content)
        print("valid JSON: True")
    except Exception as e:
        print(f"valid JSON: False ({e})")

    # also try the strict response_format if the endpoint supports it
    try:
        t0 = time.time()
        resp2 = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": 'Return {"intent": "test", "ok": true}'}],
            response_format={"type": "json_object"},
        )
        dt = time.time() - t0
        print(f"response_format=json_object supported, latency {dt:.2f}s, content: {resp2.choices[0].message.content!r}")
    except Exception as e:
        print(f"response_format=json_object NOT supported: {e}")


def test_tool_calling() -> None:
    print("\n--- tool calling ---")
    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_booking",
                "description": "Get details of a booking by id",
                "parameters": {
                    "type": "object",
                    "properties": {"booking_id": {"type": "string"}},
                    "required": ["booking_id"],
                },
            },
        }
    ]
    try:
        t0 = time.time()
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": "Look up booking B-0001 for me."}],
            tools=tools,
        )
        dt = time.time() - t0
        msg = resp.choices[0].message
        print(f"latency: {dt:.2f}s")
        print(f"tool_calls: {msg.tool_calls}")
        print(f"content: {msg.content!r}")
        print("tool calling: SUPPORTED" if msg.tool_calls else "tool calling: call succeeded but no tool_calls returned")
    except Exception as e:
        print(f"tool calling NOT supported / errored: {e}")


def test_embeddings() -> None:
    print("\n--- embeddings availability ---")
    try:
        resp = client.embeddings.create(model=MODEL, input="test sentence")
        print(f"embeddings SUPPORTED, dim={len(resp.data[0].embedding)}")
    except Exception as e:
        print(f"embeddings NOT available on this deployment: {e}")


if __name__ == "__main__":
    print(f"Testing endpoint: {BASE_URL} model: {MODEL}")
    test_basic_chat()
    test_json_mode()
    test_tool_calling()
    test_embeddings()
