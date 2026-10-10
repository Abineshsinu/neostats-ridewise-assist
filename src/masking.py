"""
PII masking for agent sessions. Column masking alone is not enough — free
text (payment remarks, damage descriptions) can contain real-looking
emails and phone numbers, so both are masked here.

Default: no reveal-unmasked feature (config flag below, default off, per
the brief — v1 ships with it off and no UI path to flip it).
"""
from __future__ import annotations

import re

REVEAL_UNMASKED = False  # v1: always off. No UI control exists to change this.

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"\b[6-9]\d{9}\b")


def mask_phone(phone: str | None) -> str | None:
    if not phone or REVEAL_UNMASKED:
        return phone
    digits = str(phone)
    return "X" * max(0, len(digits) - 4) + digits[-4:]


def mask_licence(licence: str | None) -> str | None:
    if not licence or REVEAL_UNMASKED:
        return licence
    return "X" * max(0, len(licence) - 4) + licence[-4:]


def mask_email(email: str | None) -> str | None:
    if not email or REVEAL_UNMASKED:
        return email
    if "@" not in email:
        return "***"
    local, domain = email.split("@", 1)
    if len(local) <= 1:
        return f"*@{domain}"
    return f"{local[0]}***@{domain}"


def mask_free_text(text: str | None) -> str | None:
    """Redact email/phone-like patterns inside free text columns."""
    if not text or REVEAL_UNMASKED:
        return text
    text = EMAIL_RE.sub("[redacted-email]", text)
    text = PHONE_RE.sub("[redacted-phone]", text)
    return text


def contains_injection_markers(text: str | None) -> bool:
    """Heuristic flag for instruction-like text embedded in untrusted free
    text (e.g. damage report descriptions). Used to warn agents that a
    record's free text was ignored as instructions, never executed."""
    if not text:
        return False
    markers = ["ignore previous instructions", "system note", "note to assistant", "ignore all", "you are now"]
    lowered = text.lower()
    return any(m in lowered for m in markers)
