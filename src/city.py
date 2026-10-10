"""
City name normalization. customers.city is dirty in the source data
(e.g. "Bengaluru", "Bangalore", "BLR", "bangalore " with a trailing space
all refer to the same city) — never fixed in ridewise.db itself, only
normalized in code when building a connection that groups/filters by city.
"""
from __future__ import annotations

_BENGALURU_ALIASES = {"blr", "bangalore", "bengaluru"}


def normalize_city(raw: str | None) -> str | None:
    if raw is None:
        return None
    cleaned = raw.strip()
    if cleaned.lower() in _BENGALURU_ALIASES:
        return "Bengaluru"
    return cleaned.title()
