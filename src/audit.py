"""
Audit log: one JSONL line per logged event, written to a git-ignored
logs/ folder. Records who did what, never what they said or any secret —
no raw user message text, no API keys, no unmasked PII.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_FILE = LOG_DIR / "audit.jsonl"


def log_event(
    role: str,
    customer_id: str | None,
    tool: str | None = None,
    row_count: int | None = None,
    masking_applied: bool | None = None,
    refusal_reason: str | None = None,
) -> None:
    """Append one audit event. Best-effort: a logging failure must never
    break the user-facing turn, so any exception here is swallowed."""
    try:
        LOG_DIR.mkdir(exist_ok=True)
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "role": role,
            "customer_id": customer_id if role == "customer" else "agent",
            "tool": tool,
            "row_count": row_count,
            "masking_applied": masking_applied,
            "refusal_reason": refusal_reason,
        }
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass
