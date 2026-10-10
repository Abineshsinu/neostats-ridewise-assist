# RideWise Assist

A read-only AI assistant for RideWise (a vehicle rental company) that answers customer and support-agent
questions about bookings, payments, charges and policies — using only the NeoStats-hosted LLM, the provided
SQLite database, and the five policy PDFs. No LangChain, no vector database, no external data.

## Setup (10 minutes)

### 1. Clone and create a virtual environment

**Windows (PowerShell):**
```powershell
git clone https://github.com/Abineshsinu/neostats-ridewise-assist.git
cd neostats-ridewise-assist
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

**macOS / Linux:**
```bash
git clone https://github.com/Abineshsinu/neostats-ridewise-assist.git
cd neostats-ridewise-assist
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure environment variables

Copy `.env.example` to `.env` and fill in the NeoStats-hosted LLM credentials (never commit `.env` — it's
git-ignored):

```
LLM_BASE_URL=https://your-endpoint.example.com/openai/v1/
LLM_API_KEY=your-api-key-here
LLM_MODEL=your-deployment-name
```

`LLM_MODEL` is the **deployment name** the endpoint expects in the `model` field of a chat completion call —
check your organizer-provided sample script if unsure, it may differ from the underlying model's label.

### 3. Run the app

```
streamlit run app.py
```

Open the URL Streamlit prints (usually `http://localhost:8501`). Pick **Customer** (enter a customer ID like
`CUST0001`) or **Support agent** on the start screen.

### 4. (Optional) Run the test suite

```
pytest
```

All tests pass, running offline with the LLM client mocked — no network calls, no API key required to run them.

## Architecture

```
 1. Session layer (Streamlit)
    Role + customer_id chosen ONCE at the start screen, stored server-side.
    Chat text can never change them. "New conversation" resets history;
    the sandbox connection itself is rebuilt fresh every turn (see #4).
              |
              v
 2. Guard (src/guard.py)
    Deterministic, code-only checks BEFORE any LLM call: input length,
    refuses requests for secrets/system prompt, refuses destructive
    action requests (cancel/refund/edit/delete). Chat-text role claims
    ("I am an agent now") are logged but never acted on.
              |
              v
 3. Planner (src/planner.py)
    One LLM call -> a JSON plan (intent, entities, what evidence is
    needed), validated with pydantic. Plain prompted JSON, not
    response_format=json_object (unreliable on this deployment).
              |
              v
 4. Data access (src/sandbox.py, src/data_access.py)
    Customer: an in-memory SQLite db containing ONLY that customer's own
    rows (built fresh every turn from customer_id, never persisted
    across reruns). Agent: an in-memory db over ALL rows, PII masked at
    copy time. Vetted, parameterised tools (booking lookup, refund
    estimate, late/battery fee hypotheticals, explain-a-charge) run
    against whichever connection the session has.
              |
              v
 5. Calculators (src/calculators.py) + Policy search (src/policy_search.py)
    Pure, Decimal-based functions compute refunds/fees/charges from one
    cited rules config (src/rules_config.py) — never from the LLM.
    BM25 keyword search over the 5 policy PDFs + transcribed annexures
    (no embeddings: the endpoint doesn't expose one).
              |
              v
 6. Composer (src/composer.py)
    Second LLM call. Sees ONLY the question, stated assumptions, and an
    evidence bundle (row ids + calculation steps + policy citations)
    inside <evidence> tags — told explicitly it's untrusted data, never
    instructions.
              |
              v
 7. Output check + Audit log (src/output_check.py, src/audit.py)
    Last-mile PII redaction for agent answers, flags any instruction-like
    text found in evidence. Every turn logs role/customer/tool/refusal to
    a git-ignored JSONL file — never raw message text, never secrets.
```

## Example questions

**Customer** (after entering a customer ID, e.g. `CUST0001`):
- "Show me my bookings"
- "What refund would I get if I cancel booking B-1653 now?"
- "Why was I charged extra on booking B-0554?"
- "What's the late fee for a Honda Activa 6G returned 35 minutes late if I'm GOLD tier?"
- "What if an EV scooter comes back at 7% battery?"
- "What's your cancellation policy?"

**Support agent:**
- "Tell me about booking B-0412"
- "What does the damage report for booking B-1104 say?"
- Note: cross-customer analytics (e.g. "which hub had the most damage claims last month") and the
  validated-SQL fallback are planned but ship OFF by default in this version — see DECISIONS.md.

## Project layout

```
app.py                  Streamlit UI
src/                    application code (session-independent, fully unit-tested)
  sandbox.py              per-session data isolation (customer / agent)
  data_access.py          vetted tools
  sql_validator.py        sqlglot guard for the (currently-off) SQL fallback tool
  policy_search.py        BM25 policy chunking and search
  calculators.py          pure money/time calculators
  rules_config.py         single cited source of truth for every rule value
  planner.py / composer.py / llm_client.py    the two-call LLM pipeline
  guard.py / output_check.py / audit.py       safety, redaction, logging
data/raw/               the provided PDFs, ridewise.db, data dictionary (never modified)
data/derived/           transcribed scanned-image annexures (derived, not raw)
tests/                  pytest suite (LLM always mocked)
scripts/                one-off/manual scripts (discovery, adversarial smoke test, PDF tools)
DECISIONS.md            design decisions, limitations, what's next
```

## Known limitations

See `DECISIONS.md` for the full list. In short: hub/fleet analytics for agents and the validated SQL
fallback tool are not wired into the UI yet (explicitly deferred, see DECISIONS.md); follow-up memory covers
only a small set of resolved entities (current booking, vehicle model/type, tier, delay); degraded-mode UX
(what the user sees during an LLM outage) is minimal, not polished.
