"""
Output check: a deterministic, code-level pass on the composer's final
answer text, applied after the LLM call. Two jobs:

1. Redaction safety net for agents: the agent connection already masks PII
   at copy time (src/sandbox.py), but this is a last-mile check in case
   the model echoes back something unmasked (e.g. inside a quoted
   free-text field it reasoned over). Customers are entitled to see their
   own unmasked data, so no redaction is applied for the customer role.
2. Flag (once) when any evidence record contained instruction-like text,
   so the user knows a record was disregarded as data rather than obeyed.
"""
from __future__ import annotations

from src import masking

INJECTION_NOTE = (
    "Note: one of the records used as evidence contained text written to look like an "
    "instruction to me. I treated it as plain data and ignored it."
)


def run_output_check(answer: str, role: str, evidence: list[dict]) -> tuple[str, list[str]]:
    """Returns (possibly redacted answer, list of warning notes to show)."""
    checked = answer
    warnings: list[str] = []

    if role == "agent" and checked:
        checked = masking.mask_free_text(checked)

    if _evidence_contains_injection_markers(evidence):
        warnings.append(INJECTION_NOTE)

    return checked, warnings


def _evidence_contains_injection_markers(evidence: list[dict]) -> bool:
    for item in evidence:
        for text in _text_fields(item):
            if masking.contains_injection_markers(text):
                return True
    return False


def _text_fields(item: dict) -> list[str]:
    texts: list[str] = []
    payload = item.get("payload")
    if payload is not None:
        texts.extend(_strings_in(payload))
    if "text" in item:
        texts.append(str(item.get("text") or ""))
    return texts


def _strings_in(value) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        out = []
        for v in value.values():
            out.extend(_strings_in(v))
        return out
    if isinstance(value, list):
        out = []
        for v in value:
            out.extend(_strings_in(v))
        return out
    return []
