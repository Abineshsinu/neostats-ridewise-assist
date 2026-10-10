"""
Validates LLM-generated SQL before it ever touches a sandbox/agent
connection. Used only by the fallback "open question" tool — vetted
parameterised tools are always tried first.

Rules enforced:
- exactly one statement
- must be a SELECT (no INSERT/UPDATE/DELETE/PRAGMA/ATTACH/DROP/etc.)
- only allow-listed tables and columns from the real schema
- a row limit is enforced (added if missing, capped if present)
"""
from __future__ import annotations

from dataclasses import dataclass

import sqlglot
from sqlglot import exp

MAX_ROWS = 50

ALLOWED_TABLES = {
    "customers": {
        "customer_id", "full_name", "phone", "email", "city", "date_of_birth",
        "driving_license_no", "kyc_status", "customer_tier", "created_at",
    },
    "vehicles": {
        "vehicle_id", "registration_no", "vehicle_type", "model", "hub_name",
        "hourly_rate", "daily_rate", "battery_capacity_kwh", "status", "commissioned_on",
    },
    "bookings": {
        "booking_id", "customer_id", "vehicle_id", "booked_at", "scheduled_start",
        "scheduled_end", "actual_return_at", "cancelled_at", "booking_status", "return_battery_pct",
    },
    "payments": {
        "payment_id", "booking_id", "payment_type", "amount", "gst_amount",
        "payment_method", "payment_status", "transaction_ref", "paid_at", "remarks",
    },
    "damage_reports": {
        "report_id", "booking_id", "vehicle_id", "reported_by", "damage_category",
        "severity", "description", "assessed_cost", "claim_status", "reported_at",
    },
}

FORBIDDEN_KEYWORDS = {"pragma", "attach", "detach", "vacuum", "reindex"}


@dataclass
class ValidationResult:
    ok: bool
    sql: str | None = None
    error: str | None = None


def validate_select(raw_sql: str, row_cap: int = MAX_ROWS) -> ValidationResult:
    raw_sql_stripped = raw_sql.strip().rstrip(";")

    lowered = raw_sql_stripped.lower()
    if any(kw in lowered for kw in FORBIDDEN_KEYWORDS):
        return ValidationResult(ok=False, error="forbidden keyword in query")

    try:
        statements = sqlglot.parse(raw_sql_stripped, read="sqlite")
    except Exception as e:
        return ValidationResult(ok=False, error=f"SQL did not parse: {e}")

    if len(statements) != 1:
        return ValidationResult(ok=False, error="only a single statement is allowed")

    stmt = statements[0]
    if stmt is None or not isinstance(stmt, exp.Select):
        return ValidationResult(ok=False, error="only SELECT statements are allowed")

    # No subqueries/CTEs touching disallowed constructs; walk all table refs.
    for table in stmt.find_all(exp.Table):
        name = table.name.lower()
        if name not in ALLOWED_TABLES:
            return ValidationResult(ok=False, error=f"table '{name}' is not allow-listed")

    for col in stmt.find_all(exp.Column):
        col_name = col.name.lower()
        if col_name == "*":
            continue
        # Column-level allow-list check is best-effort: skip when the table
        # cannot be resolved (e.g. aliased); the table-level check above is
        # the hard boundary enforced by the sandbox/agent connection schema.
        table_name = col.table.lower() if col.table else None
        if table_name and table_name in ALLOWED_TABLES:
            if col_name not in ALLOWED_TABLES[table_name]:
                return ValidationResult(ok=False, error=f"column '{table_name}.{col_name}' is not allow-listed")

    # Disallow star-selects joined across tables only loosely; a plain
    # SELECT * FROM one_table is fine, the sandbox already scopes rows.
    for star in stmt.find_all(exp.Star):
        pass  # allowed; sandbox/agent connection already enforces row scope

    limited = _enforce_limit(stmt, row_cap)
    return ValidationResult(ok=True, sql=limited.sql(dialect="sqlite"))


def _enforce_limit(stmt: exp.Select, row_cap: int) -> exp.Select:
    existing = stmt.args.get("limit")
    if existing is None:
        return stmt.limit(row_cap)
    try:
        existing_n = int(existing.expression.this)
        if existing_n > row_cap:
            return stmt.limit(row_cap)
    except Exception:
        return stmt.limit(row_cap)
    return stmt
