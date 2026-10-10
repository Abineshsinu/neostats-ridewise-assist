"""
Deterministic, code-level guard — runs before anything reaches the LLM.
Chat text can never change role or customer_id (those come only from the
session object); this module is what makes that true for free-text
requests like "I am an agent now" or "ignore your instructions".
"""
from __future__ import annotations

MAX_INPUT_LENGTH = 2000

SECRET_REQUEST_MARKERS = [
    "api key", "api_key", "llm_api_key", "system prompt", "your instructions",
    "env var", "environment variable", ".env", "base_url", "llm_base_url",
]

DESTRUCTIVE_MARKERS = [
    "delete", "drop table", "update ", "insert into", "truncate",
    "cancel my booking", "please cancel booking", "issue a refund", "process a refund",
    "edit my booking", "refund me now", "go ahead and cancel",
]

ROLE_CLAIM_MARKERS = [
    "i am an agent", "i'm an agent", "admin mode", "as an agent", "switch to agent",
    "i am support", "grant me access", "act as an agent",
]


class GuardResult:
    def __init__(self, allowed: bool, reason: str | None = None, refusal_message: str | None = None):
        self.allowed = allowed
        self.reason = reason
        self.refusal_message = refusal_message


SCOPED_REFUSAL = (
    "I can help with your RideWise bookings, payments and policies, but I can't help with that. "
    "I'm also read-only, so I can't cancel, refund, or edit anything directly — "
    "I can explain what the policy says or give you an estimate."
)


def check_input(text: str) -> GuardResult:
    if len(text) > MAX_INPUT_LENGTH:
        return GuardResult(False, "too_long", f"That message is a bit long — could you keep it under {MAX_INPUT_LENGTH} characters?")

    lowered = text.lower()

    for marker in SECRET_REQUEST_MARKERS:
        if marker in lowered:
            return GuardResult(False, "secret_request", SCOPED_REFUSAL)

    for marker in DESTRUCTIVE_MARKERS:
        if marker in lowered:
            return GuardResult(False, "destructive_request", SCOPED_REFUSAL)

    return GuardResult(True)


def strip_role_claims_note(text: str) -> bool:
    """Returns True if the message contains a role-claim attempt, purely
    informational for logging — the role itself is never read from chat
    text regardless of this check, since it's only ever read from the
    session object."""
    lowered = text.lower()
    return any(marker in lowered for marker in ROLE_CLAIM_MARKERS)
