# DECISIONS.md

## Three most important design decisions, and why

**1. Customer data isolation is structural, not a query filter.**
A customer's session runs against a fresh, private in-memory SQLite database containing *only* that
customer's own rows, rebuilt from `customer_id` at the start of every turn (`src/sandbox.py`). No other
customer's row is ever loaded into that connection. This means a booking belonging to another customer and a
booking that doesn't exist at all are literally the same event from inside that connection — a failed
`SELECT` — so "same refusal whether it exists or not" falls out of the architecture for free, rather than
needing to be carefully gotten right in an `if/else` somewhere. **Alternative considered and rejected:** a
single shared connection with `WHERE customer_id = ?` filters added to every query. Rejected because it
depends on every current and future query remembering the filter — one missed `WHERE` clause in a
fallback/generated-SQL path is a real leak, whereas a row that was never copied in cannot leak no matter what
SQL runs against it.

**2. BM25 keyword search over cited, versioned policy chunks, not embeddings.**
The brief allowed embeddings (a local open-source model, if the provider didn't offer one). We checked first
and found the hosted endpoint has no embeddings route at all (a direct API call returns 404), so the choice
came down to standing up a second, separate local embedding model versus keyword search. We chose BM25 for
two concrete reasons: it adds no new moving part to set up and keep stable under a tight time budget, and it
keeps every retrieved chunk traceable to an exact document/section by construction, which matters directly
for the transparency requirement. Five short, mostly well-structured policy PDFs don't need semantic
matching to be found reliably. **Trade-off accepted:** a paraphrased question with none of the document's own
wording (e.g. "what happens to my money if I bail last minute") would rank worse under BM25 than it would
under embeddings — this is a real limitation, not a free win.

**3. Calculators are pure functions with no database or LLM access, and every one returns its own working.**
`src/calculators.py` takes plain numbers in, returns a value plus a step-by-step string trail and the policy
citation used. The LLM never computes a number — it only explains numbers the calculators already produced.
**Alternative considered and rejected:** letting the composer LLM do the arithmetic directly from retrieved
policy text. Rejected after manual testing (after the first working version of the app was in place) caught
the model mislabeling a raw UTC timestamp "(IST)" in its answer without actually converting it — it had
copied the stored value and just appended a timezone label. If it can't be trusted to copy a timezone
conversion correctly, it can't be trusted to apply a GST percentage or a late-fee slab boundary correctly
either. Every number in this app traces back to `src/rules_config.py` and a deterministic function, never to
the model's own math.

## Where the assistant currently fails or behaves poorly

- **There is no real authentication.** A customer session is started by typing a customer ID with no password
  or verification step — anyone who knows or guesses a valid ID (e.g. `CUST0001`) can open that customer's
  session. This is explicitly out of scope for this exercise but is a genuine gap for any real deployment.
- **The three scanned-image annexures were transcribed by hand, not programmatically.** The v2 refund table,
  the GOLD tier-grace table, and the EV battery-fee figure were extracted as images and read visually, then
  typed into `data/derived/policy_annexures.md` with a manual cross-check against the values stated in the
  task brief. If a future policy update changes one of these images, the transcription has to be redone by
  hand — there's no OCR or automated re-extraction step.
- **The planner sometimes misroutes a question to the wrong intent.** Because intent classification is a
  single LLM call producing a label like `charge_explain` or `booking_lookup`, a question phrased
  unusually can get the wrong label and therefore the wrong tool — e.g. early in development, "what does my
  damage report say" was initially routed to a generic booking lookup (which doesn't surface damage details)
  rather than `charge_explain`, simply because that intent name wasn't yet in the planner's own prompt
  vocabulary. That specific case is now fixed, but the class of failure (an intent label the prompt didn't
  anticipate) is not eliminated.
- **Agent-side analytics and the SQL fallback tool are not wired into the UI.** Hub damage-claim counts,
  masked customer lookup by an agent, and the validated LLM-written-SQL fallback for open-ended agent
  questions were deliberately held back to protect stability ahead of the deadline. An agent asking "which hub
  had the most damage claims last month" today gets routed through the generic vetted tools, which don't cover
  that question — the assistant will likely say it can't find evidence, rather than compute the real answer.
- **Follow-up memory is intentionally narrow.** Only a small set of resolved entities (current booking,
  vehicle model/type, tier, delay minutes, battery percent) persist across turns, managed in code
  (`src/orchestrator.py`), not by the LLM. A follow-up that depends on something outside that list (e.g. "and
  for the one before that?" referring to an earlier booking mentioned three turns ago) will likely lose
  context.
- **The chunking/retrieval quality for generic policy questions is imperfect.** A plain "what's the refund
  policy" query sometimes ranks a short, keyword-dense section (e.g. "cancellation by RideWise: 100% refund")
  above the longer slab table that's actually the primary answer. The composer still has the right chunk in
  its evidence (top 3–5), so the final answer is usually still correct, but the ranking itself isn't
  perfectly precision-tuned.
- **Degraded-mode UX is minimal.** If the LLM endpoint is down, the user gets a plain fallback message
  (`src/llm_client.py`), not a polished "try again" experience with retry affordances in the UI itself.
- **No rate limiting or per-session request caps** beyond the LLM client's own retry/backoff — a user could
  spam the chat input and generate many LLM calls in quick succession.
- **Several things are genuinely unspecified in the provided documents, and the assistant is built to say so
  rather than guess** (see `src/rules_config.py`'s `UNSPECIFIED` list): the EV recovery/towing charge amount
  (the FAQ mentions "a recovery charge may apply" with no figure), the thresholds for qualifying into the
  SILVER/GOLD customer tiers, and what counts as a "working day" or holiday for the refund/deposit processing
  timelines.

## What I would build next with one more week

1. **Wire the two deferred agent-side items**: hub damage-claim analytics for agents (joining `damage_reports`
   through `vehicles.hub_name`, stating the exact IST date window used, handling ties), and the validated
   SQL fallback tool behind its off-by-default flag, with enough adversarial testing (via `sqlglot` plus a
   SQLite authorizer) to turn it on with confidence.
2. **Tune policy retrieval** with a lightweight re-ranking step — e.g. boosting a chunk that contains a
   percentage-and-hours table when the query mentions a duration, since BM25 alone under-weights long,
   information-dense sections relative to short, keyword-repetitive ones.
3. **Broaden follow-up memory** to a short structured history of recently-discussed bookings/entities rather
   than a flat dict of "current" values, so a user can refer back to something from a few turns ago without
   restating it.
4. **Add a proper degraded-mode UI state** — a visible banner when the LLM is unavailable, with the
   deterministic calculators/tools still answering what they can, instead of a single fallback sentence.
5. **Expand the reconciliation and adversarial test suite** to run as a scheduled/CI check against the real
   `ridewise.db`, so a future data-pack update (a new policy PDF, a schema tweak) gets caught automatically
   rather than requiring another manual audit from scratch.
