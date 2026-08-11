# Waste-rate Metric — Toolathlon Adapter Amendment (Pre-registration)

**Status.** Pre-registration amendment to
`docs/WASTE_RATE_METRIC_PREREG.md`. Per `feedback_rule_8`, this
document is pushed and PR-opened before any adapter code, measurement
script, or reporting code lands. The reconstruction rule, apportionment
formula, and Corpus B re-scan predictions below are the pre-committed
frozen positions; adjusting them after seeing results is not allowed.

**Motivation.** `WASTE_RATE_METRIC_PREREG.md` §13.2 documented that all
6,780 Toolathlon trajectories were excluded from the metric on the
2026-08-10 scan because `src/clew/ingest/toolathlon.py` emits tool
spans only and does not populate `trace.metadata["llm_calls"]`. §13.2
explicitly deferred "extending the Toolathlon adapter to reconstruct
pseudo-LLM-calls" to a separate amendment. This is that amendment.

## 0. Honesty preface (what this amendment is and is not)

**What this amendment does:**

- Extends `src/clew/ingest/toolathlon.py` to reconstruct per-assistant
  LLM calls from Toolathlon JSONL `messages`, populating
  `trace.metadata["llm_calls"]` in the CC-adapter-compatible shape.
- Apportions the trace-level `key_stats.input_tokens` /
  `output_tokens` across reconstructed calls by input-text-length
  weight, using the same cost lookup path CC uses.
- Re-runs the Waste-rate metric (unchanged §1 spec, unchanged §3
  detector set) on the same Toolathlon corpus manifest from §13.2.

**What this amendment does NOT do:**

- Does not change the metric spec (`WASTE_RATE_METRIC_PREREG.md` §1),
  detector set (§3), aggregation rule (§4), or session threshold (§5).
- Does not add a new detector or a new pitch statistic.
- Does not claim the reconstructed LLM calls are a faithful replica of
  what Toolathlon actually sent to the provider. They are a
  best-effort reconstruction from the trajectory record. §4 quantifies
  the reconstruction fidelity check.
- Does not claim the resulting numbers are a benchmark validation. The
  honest expectation (§5) is that the metric will re-confirm the
  Context Resend dominance already seen on Corpus A. New numbers on
  Toolathlon are a **re-confirmation**, not a **new detector signal**.

## 1. Reconstruction rule (frozen)

### 1.1 One LLM call per assistant message

For each Toolathlon trajectory (one JSONL line), iterate its
`messages` list in order and emit one entry in
`trace.metadata["llm_calls"]` per message with `role == "assistant"`.
User messages and tool messages are not LLM calls; they contribute to
the accumulated context of the next assistant call.

The number of reconstructed LLM calls per trajectory must equal
`key_stats.agent_llm_requests` when both are populated; if they differ
the trace is excluded with `excluded_reason="llm_call_count_mismatch"`
(cross-check in §4).

### 1.2 `input_text` = accumulated prior messages, JSON-serialized

For the k-th assistant message (0-indexed) in the trajectory, the
`input_text` is `json.dumps(prior_messages, ensure_ascii=False,
default=str, sort_keys=False)` where `prior_messages` is the list of
all messages at positions `0..k-1` in trajectory order, filtered to
`role in {"user", "assistant", "tool"}` and each entry restricted to
the fields the LLM would have received:

- `user`: `{"role": "user", "content": <content>}`
- `assistant`: `{"role": "assistant", "content": <content>,
  "tool_calls": <tool_calls>}` when `tool_calls` is present, else no
  `tool_calls` field
- `tool`: `{"role": "tool", "content": <content>, "tool_call_id":
  <id>}`

Content is passed through as-is (whether string or list of blocks)
without normalization. This matches the CC adapter's convention
(`_extract_llm_calls` at `src/clew/ingest/claude_code.py:239`) which
serializes accumulated messages verbatim.

Rationale: LLM APIs receive the full accumulated context each call.
Bytes-in-context = bytes-billed-as-input (approximately). Using the
accumulated context is what makes Context Resend detectable at all —
the whole point of the detector is that most of each call's input is
a re-transmission of prior turns.

### 1.3 Token apportionment (length-weighted)

Trace-level aggregates from `key_stats` (JSON string field on the
JSONL entry, parsed):

- `T_in = key_stats.input_tokens`
- `T_out = key_stats.output_tokens`
- `N_req = key_stats.agent_llm_requests`

For each reconstructed llm_call `c_i` with `input_text` of UTF-8 byte
length `L_i`:

```
input_tokens_i  = round(T_in  * L_i / sum(L_j))
output_tokens_i = round(T_out * 1   / N_req)   # equal split
```

Input tokens are apportioned by accumulated-context length because
that is what actually drives per-call billing under a
non-cache-hit-heavy usage pattern. Output tokens are split equally
because the trajectory does not expose per-assistant output length
directly (assistant `content` may be a list of blocks including
tool_calls; extracting a canonical "assistant text output length"
would require a normalization pass this amendment does not introduce).

If `sum(L_j) == 0` (every assistant is the very first message with no
prior context, a pathological but possible case), token apportionment
falls back to equal split for both.

**Rounding invariant.** `input_tokens_i` values are computed by
`round(...)` per call; the sum may differ from `T_in` by up to N_req
tokens. The last call absorbs the residual so that
`sum(input_tokens_i) == T_in` exactly. Same for `output_tokens_i`.

### 1.4 Cache-tier fields set to zero

Toolathlon's `key_stats` does not distinguish cached vs uncached
input tokens. All apportioned input tokens are assigned to the
uncached tier:

```
input_tokens_uncached_i    = input_tokens_i
input_tokens_cache_read_i  = 0
input_tokens_cache_write_i = 0
```

This is a conservative choice: cost tables typically price uncached
input higher than cached, so this over-estimates cost per trace. The
overestimation is bounded by the cache-read discount for the specific
model (typically 10-25% off uncached rate). Documented as a
non-commitment in §7.

### 1.5 Cost rate lookup (unchanged from CC)

`input_cost_rate` and `output_cost_rate` are looked up by
`modelname_run` in the same cost tables the CC adapter consults. If
`modelname_run` is not present in the cost table, both rates are
`None` and WR_cost falls back to the existing §1.2 exclusion path
(trace excluded from WR_cost aggregate, still included in WR_char).

The cost table is not extended for this amendment. If a Toolathlon
model is not currently priced, its trajectories are WR_cost-excluded
by the existing rule.

### 1.6 `span_id`, `start_time`, `model`

- `span_id = f"toolathlon-llm-{k:06d}"` where k is the 0-indexed
  position of the assistant message in the trajectory.
- `start_time`: reuse the synthetic timestamp scheme already in
  `toolathlon.py` (§23.2), computed as `_synth_ts(k, 0)` where k is
  the message index — one second before the assistant's tool_call
  spans at `_synth_ts(k, sub_idx>=1)`, preserving sort order.
- `model = modelname_run`.

## 2. Corpus (frozen — same as `WASTE_RATE_METRIC_PREREG.md` §2.2)

- **Manifest sha256:**
  `9648d18876685ae54ee20abcb88e191f0914f20f2025ff38a9d2cedb0699d4f7`
- **Files:** 66 JSONL (22 models × 3 runs)
- **Trajectories:** 6,780

No new data is added. The re-scan uses the identical manifest.

## 3. What is not changed

- `docs/WASTE_RATE_METRIC_PREREG.md` §1 metric definitions —
  unchanged.
- §3 detector set (context_resend, repeat, redundant_read,
  duplicate_creation) — unchanged.
- §4 aggregation rule — unchanged.
- §5 session threshold (SDR@10) — unchanged.
- §6.1 report integration — unchanged; the report already exposes
  waste_rate. This amendment only fills in Toolathlon numbers.
- CC adapter (`src/clew/ingest/claude_code.py`) — untouched.
- Corpus A (28 CC sessions) — no re-scan required. §13.1 numbers
  stand.

## 4. Reconstruction fidelity check (frozen)

Before reporting waste-rate numbers on Toolathlon, the amendment
diagnostic script must verify, per trajectory:

- **Count match:** `len(llm_calls) == key_stats.agent_llm_requests`.
  Mismatches are excluded with `excluded_reason="llm_call_count_mismatch"`
  and counted in the results table.
- **Token sum match:** `sum(input_tokens_i) == T_in` and
  `sum(output_tokens_i) == T_out` (rounding residual absorbed in
  final call per §1.3).
- **`agent_cost.total_cost` sanity:** if the model is in the cost
  table, compute
  `predicted_cost = sum(input_tokens_i * input_cost_rate) +
  sum(output_tokens_i * output_cost_rate)`
  and report the ratio `predicted_cost / agent_cost.total_cost`
  per-trajectory. If the median ratio across included trajectories
  falls outside `[0.5, 2.0]`, the amendment is flagged for
  post-hoc review in the results section (§9) with the honest
  observation that reconstruction cost diverges materially from
  provider-reported cost. Note: this is a **reporting** trigger, not
  a Go/No-go gate — the metric still reports whatever it computes.

## 5. Predictions (pre-committed)

The following predictions are recorded here so post-hoc results can be
compared against pre-registered expectations, per the standard prereg
discipline in this repo.

**P1.** `union_wr_char` on Toolathlon will fall in **[0.85, 0.999]**,
dominated by `context_resend`. Rationale: reconstructed LLM calls have
accumulated-context inputs; Context Resend measures byte overlap
across consecutive call inputs; long accumulated contexts have high
overlap by construction.

**P2.** `union_sdr_at_10` on Toolathlon will fall in **[0.85, 1.00]**.
Rationale: the 10% threshold is trivially exceeded once accumulated
context accounts for >90% of any call's input, which is the typical
regime for multi-turn tool-use trajectories.

**P3.** `union_wr_cost` on Toolathlon will fall in **[0.10, 0.50]**,
strictly less than `union_wr_char`. Rationale: same 3× char-vs-cost
divergence pattern observed on Corpus A (§13.4.1) will apply here.

**P4.** Per-detector: `context_resend` accounts for ≥ 95% of the
union numerator; `repeat` and `duplicate_creation` may fire on
Toolathlon (tool-side detectors, orthogonal to LLM-call
reconstruction); `redundant_read` will remain near 0 because
Toolathlon tasks are not filesystem-heavy.

**What would violate expectations (would trigger honest §9 note):**

- Any metric falling outside its P1/P2/P3 band.
- Median `predicted_cost / agent_cost.total_cost` outside `[0.5, 2.0]`
  (§4 flag).
- `context_resend` accounting for less than 95% of the union
  numerator (would suggest the reconstruction rule is materially
  altering detector behavior in an unexpected way).

Meeting all predictions is not evidence of correctness — it is
consistent-with-expectation. Missing them triggers a diagnostic
section but does not invalidate the metric.

## 6. Method

1. Implement the reconstruction rule in
   `src/clew/ingest/toolathlon.py` per §1. New helper
   `_reconstruct_llm_calls(messages, key_stats, agent_cost,
   modelname_run, cost_tables)` returning the same shape as CC's
   `_extract_llm_calls`.
2. Add unit tests in `tests/ingest/test_toolathlon.py` (existing
   file) covering: (a) count match with `agent_llm_requests`, (b)
   token sum invariant, (c) length-weighted apportionment, (d)
   fallback to equal split when accumulated-context lengths are all
   zero, (e) cost rate `None` when model not in table.
3. Run the amendment diagnostic
   `field_test/diagnostics/waste_rate_metric_toolathlon_v2.py`
   (uncommitted, per `feedback_diagnostics_uncommitted`) against the
   frozen manifest.
4. Append results as §9 of this document.

## 7. Explicit non-commitments

- Not committing to a specific LLM-call count per trajectory — the
  reconstruction infers from message order.
- Not committing to a per-call output-length attribution scheme
  beyond equal split. A future amendment may refine this.
- Not committing that the reconstructed `input_text` matches what
  Toolathlon actually sent to the provider byte-for-byte. Providers
  may add system prompts, tool-use scaffolding, or role
  concatenation the trajectory does not record.
- Not committing that WR_cost on Toolathlon will match
  `agent_cost.total_cost`. §4 records the divergence honestly.
- Not committing that this amendment makes the Waste-rate metric
  benchmark-suitable for Toolathlon. It makes it computable. Whether
  the resulting numbers are decision-relevant is a separate
  question the results section will address.

## 8. Backout plan

If the reconstruction rule produces reconstruction fidelity outside
§4's sanity band (median ratio outside `[0.5, 2.0]`), or if
predictions P1-P4 all miss simultaneously, the honest response is to
document the outcome in §9 and leave the adapter change in place with
a diagnostic note. Reverting the adapter is not necessary — the
metric spec (`WASTE_RATE_METRIC_PREREG.md` §1) already gracefully
handles unpriced/empty cases. The amendment is scoped so a "bad
outcome" is observable rather than blocking.

## 9. Commit chain (per `feedback_rule_8`)

Three commits, no squash/rebase:

1. `docs: Waste-rate Metric Toolathlon adapter amendment prereg` —
   this file only. PR opened for approval.
2. **After approval:** `feat(ingest): Toolathlon LLM call
   reconstruction per amendment §1` — `src/clew/ingest/toolathlon.py`
   + `tests/ingest/test_toolathlon.py`.
3. `docs(waste_rate): append §9 Toolathlon amendment results` —
   append executed results section below.

## 10. Results (Toolathlon re-scan — to be appended after code lands)

_To be appended._
