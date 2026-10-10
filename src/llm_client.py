"""
Thin wrapper around the NeoStats-hosted OpenAI-compatible endpoint.

Resilience (brief requirement: stay usable if the LLM is slow, rate-limited
or unavailable):
- a request timeout
- one retry with backoff on timeout / 429 / 5xx / empty content
- generous max_tokens, because this endpoint's hidden reasoning (gpt-oss
  style) consumes completion tokens even when nothing is returned — a
  short cap can silently truncate the visible answer to nothing
- callers get a structured LLMResult with ok=False and a friendly message
  on failure, never a raised exception that could crash the UI
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass

from dotenv import load_dotenv
from openai import OpenAI, APIError, APITimeoutError, RateLimitError

load_dotenv()

DEFAULT_TIMEOUT_SECONDS = 20
DEFAULT_MAX_TOKENS = 1024
FALLBACK_MESSAGE = (
    "I'm having trouble reaching the assistant service right now. "
    "Please try again in a moment, or contact RideWise Support at "
    "support@ridewise.example / +91 80 4000 1234 (7:00 AM to 11:00 PM IST)."
)


@dataclass
class LLMResult:
    ok: bool
    content: str | None = None
    raw_tool_calls: list | None = None
    error: str | None = None


class LLMClient:
    def __init__(self) -> None:
        self.base_url = os.environ.get("LLM_BASE_URL")
        self.api_key = os.environ.get("LLM_API_KEY")
        self.model = os.environ.get("LLM_MODEL")
        self._client = None
        if self.base_url and self.api_key and self.model:
            self._client = OpenAI(base_url=self.base_url, api_key=self.api_key, timeout=DEFAULT_TIMEOUT_SECONDS)

    def available(self) -> bool:
        return self._client is not None

    def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        max_calls: int = 2,
    ) -> LLMResult:
        """One resilient chat call with one retry on transient failure or
        empty content. Never raises — returns LLMResult(ok=False, ...) with
        a friendly fallback message instead."""
        if not self.available():
            return LLMResult(ok=False, error="LLM not configured", content=FALLBACK_MESSAGE)

        last_error = None
        for attempt in range(max_calls):
            try:
                kwargs = {"model": self.model, "messages": messages, "max_tokens": max_tokens}
                if tools:
                    kwargs["tools"] = tools
                resp = self._client.chat.completions.create(**kwargs)
                msg = resp.choices[0].message
                content = (msg.content or "").strip()
                tool_calls = getattr(msg, "tool_calls", None)
                if content or tool_calls:
                    return LLMResult(ok=True, content=content or None, raw_tool_calls=tool_calls)
                last_error = "empty response content"
            except (APITimeoutError, RateLimitError) as e:
                last_error = f"{type(e).__name__}: {e}"
                time.sleep(min(2 ** attempt, 4))
            except APIError as e:
                last_error = f"APIError: {e}"
                time.sleep(min(2 ** attempt, 4))
            except Exception as e:
                last_error = f"{type(e).__name__}: {e}"
                break

        return LLMResult(ok=False, error=last_error, content=FALLBACK_MESSAGE)
