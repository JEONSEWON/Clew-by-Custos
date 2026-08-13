# Waste-rate Metric — Exgentic Adapter Amendment (Pre-registration)

**Status.** Pre-registration amendment to
`docs/WASTE_RATE_METRIC_PREREG.md`. Per `feedback_rule_8`, this
document is pushed and PR-opened before any committed adapter code
or measurement script lands. The reconstruction rule and re-run
prediction bands below are the frozen positions; adjusting them
after seeing the committed-adapter re-run is not allowed.

**Motivation.** `WASTE_RATE_METRIC_PREREG.md` §1 defines the metric
against corpora with either Claude-Code JSONL or Toolathlon JSONL
ingest paths. This amendment adds a third corpus: **Corpus C ·
Exgentic Agent LLM Traces v2** (Hugging Face
`Exgentic/agent-llm-traces-v2` · 10,057 sessions · 241,674 spans
across 6 benchmarks and 5 canonical models). The dataset uses OTel
GenAI semantic conventions (`gen_ai.*` attributes) which Clew's
existing ingest paths do not consume directly; this amendment
specifies the namespace bridge, session boundary handling, and
scope constraint.

## 0. Honesty preface (what this amendment is and is not)

**What this amendment does:**

- Adds `src/clew/ingest/exgentic.py`, a committed adapter that reads
  Exgentic parquet rows and produces `Trace` objects with the same
  `llm_calls` shape the existing four deterministic detectors already
  consume.
- Bridges the OTel GenAI attribute namespace (`gen_ai.usage.*`,
  `gen_ai.request.model`, `gen_ai.input.messages`) to the
  OpenInference names Clew reads today (`llm.token_count.*`,
  `llm.model_name`, `input.value` / `output.value`).
- Synthesizes a per-session CHAIN root span so the Format-A ingest
  path terminates (Exgentic's chat spans all reference parents that
  were filtered out by the dataset builder — §Filtering step 3 of
  the dataset README).
- Handles the multi-`trace_id` case (0.07% of the corpus per Day 3
  diagnostic) rather than raising `single trace_id` errors.
- Re-runs the Waste-rate metric on the same 10,056 sessions using
  the committed adapter (no metric definition change).

**What this amendment does NOT do:**

- Does not change `docs/WASTE_RATE_METRIC_PREREG.md` §1 metric
  definitions, §3 detector set, or §4 aggregation rules.
- Does not modify Corpus A or Corpus B numbers. Corpus A
  `WR_char = 0.9930 · WR_cost = 0.2903` and Corpus B
  `WR_char = 0.9342 · WR_cost = 0.9189` stand.
- Does not add a new detector. The four existing deterministic
  detectors are applied unchanged; only three of them (repeat,
  redundant_read, duplicate_creation) collapse to zero on Corpus C
  by structural absence — see §1.5.
- Does not modify LLM-judge rubric v1. Corpus C LLM-judge results
  belong to a separate follow-up chain (§7).
- Does not commit the Day 3 diagnostic numbers (`exgentic_day3_full_scan.py`
  outputs) as authoritative results. Those informed the prediction
  bands below; the committed-adapter re-run (§5) validates them.

## 1. Adapter contract (frozen)

### 1.1 Ingest entry point

New module `src/clew/ingest/exgentic.py` exposing:

```python
def ingest_exgentic_row(
    row: dict[str, Any],
    *,
    cost_table: dict[str, float] | None = None,
    input_cost_table: dict[str, float] | None = None,
    output_cost_table: dict[str, float] | None = None,
) -> Trace: ...

def ingest_exgentic_parquet_iter(
    path: Path,
    *,
    input_cost_table: dict[str, float] | None = None,
    output_cost_table: dict[str, float] | None = None,
) -> Iterator[Trace]: ...
```

Both call the same core translator. The parquet iterator opens the
file once and yields one Trace per row.

### 1.2 Attribute namespace bridge

For each Exgentic span, the following mapping is applied:

| Exgentic (OTel GenAI) | Clew (OpenInference) | Notes |
|---|---|---|
| `gen_ai.usage.input_tokens` (int) | `llm.token_count.prompt` | |
| `gen_ai.usage.output_tokens` (int) | `llm.token_count.completion` | |
| sum of the two | `llm.token_count.total` | Derived when both present |
| `gen_ai.request.model` | `llm.model_name` | Fallback to `gen_ai.response.model` when request missing |
| `gen_ai.input.messages` (JSON string) | `input.value` | Preserved as-is (byte payload the caller would re-send) |
| `gen_ai.output.messages` (JSON string) | `output.value` | |
| — | `openinference.span.kind = "LLM"` | Every chat span is LLM-kind |

Cache tier fields (`llm.token_count.prompt.cache_read` /
`cache_write`) are **not populated.** Exgentic does not record cache
tier data; per Corpus B §1.4 parity, cache tier absence propagates
to `input_tokens_cache_read = None` / `input_tokens_cache_write = None`
on every reconstructed llm_call. `cost_accuracy_flag` therefore
reports `"estimated"` on every Corpus C session (documented; not
a defect).

### 1.3 Session boundary (synthetic CHAIN root)

Exgentic sessions filter out `invoke_agent` and `execute_tool` spans
(dataset README §Filtering step 3). Every chat span in a session
points to a parent that is not present in the span list.

The adapter synthesizes exactly one CHAIN root per session:

```python
synth_root = {
    "context": {
        "trace_id": <session-primary trace_id, §1.4>,
        "span_id":  <hash(session_id)[:16]>,
    },
    "parent_id": None,
    "name": f"session {session_id}",
    "start_time": min(span.start_time for span in session),
    "end_time":   max(span.end_time   for span in session),
    "attributes": {"openinference.span.kind": "CHAIN"},
}
```

Every chat span in the session is re-parented to this synthetic root.
The primary `trace_id` (see §1.4) becomes the trace-level identifier.

### 1.4 Multi trace_id handling

Some Exgentic sessions (7 / 10,056 on the Day 3 diagnostic = 0.07%)
contain spans with more than one distinct `trace_id`, likely arising
from cross-trace sub-agent invocations that survived the chat-only
filter.

**Adapter rule:** the primary `trace_id` is the one carried by the
majority of chat spans in the session (mode of `span.trace_id`,
first-seen tiebreak). All spans are re-parented to the synthetic
root and share the primary `trace_id`. The original per-span
`trace_id` is not preserved; a session-level metadata field
`exgentic.trace_id_secondary_count` records how many minority
`trace_id` values were collapsed, so downstream code can flag
sessions where cross-trace structure existed.

### 1.5 Chat-only scope

Every Exgentic span has `gen_ai.operation.name == "chat"`. Tool
spans (`execute_tool`) and agent-orchestration spans
(`invoke_agent`) were removed by the dataset builder (dataset
README §Filtering step 3). This has two structural consequences on
the four deterministic detectors:

- **`context_resend`** (input-text comparison across successive LLM
  calls) — applies fully. This is the only detector that produces
  non-zero output on Corpus C.
- **`repeat` / `requery`** (tool-input-repetition) — structurally
  zero. No tool spans exist to repeat.
- **`redundant_read`** (Read-tool duplicate calls) — structurally
  zero. No Read tool spans exist.
- **`duplicate_creation`** (creation-tool ID-bridge) — structurally
  zero. No creation tool spans exist.

The metric aggregation across four detectors (§4 of the parent
prereg) is applied unchanged; three detectors returning zero is a
correct outcome of the aggregation rule on Corpus C, not a defect.
Union numbers on Corpus C therefore equal the `context_resend`
numbers.

### 1.6 Cost pricing dependency

The adapter passes `input_cost_table` / `output_cost_table` through
to the same rate resolution path used by the Toolathlon and
Claude-Code adapters. The 5 canonical Exgentic model names
(`DeepSeek-V3.2`, `Kimi-K2.5`, `claude-opus-4-5`,
`gemini-3-pro-preview`, `gpt-5.2-2025-12-11`) must resolve to
correct canonical pricing keys after the Cost Table Exgentic
Expansion (PRs #100 / #101 / #102). This amendment does not
re-verify the pricing table; §5 lists a pre-flight assertion that
zero `unknown model` warnings fire on Corpus C.

## 2. Metric definitions (unchanged)

- `wr_char`, `wr_cost`, `union_wr_char`, `union_wr_cost`, `SDR@10`
  as defined in `WASTE_RATE_METRIC_PREREG.md` §1.
- Uncached-tier billing assumption per parent §1.5; Corpus C
  inherits this by the same rationale as Corpus B (no cache tier
  data in the source).

## 3. What is not changed

- `docs/WASTE_RATE_METRIC_PREREG.md` — unchanged.
- `docs/WASTE_RATE_TOOLATHLON_ADAPTER_AMENDMENT_PREREG.md` —
  unchanged.
- `docs/COST_TABLE_TOOLATHLON_EXPANSION_PREREG.md` and
  `docs/COST_TABLE_EXGENTIC_EXPANSION_PREREG.md` — unchanged.
- Detector code (`src/clew/detect/*.py`) — unchanged.
- Existing ingest paths (`claude_code.py`, `toolathlon.py`,
  `otel_json.py`, `redundancy_bench.py`, `langgraph.py`) —
  unchanged.
- Pricing table — unchanged (Cost Table Exgentic Expansion already
  merged).
- Corpus A and Corpus B numbers — unchanged.

## 4. Predictions (pre-committed)

**Framing lesson from Cost Table Exgentic Expansion §9.5** (Rule 8
chain 3 · PR #102): per-session `wr_cost` under the uncached-only
path is byte-equivalent to `wr_char` because rate cancels between
numerator and denominator on single-model sessions. Aggregate
prediction bands here are framed as **union** (`sum(resent_i) /
sum(total_i)` across all Corpus C sessions), not per-session
medians. Per-session distribution statistics are reported alongside
but are not the primary target.

The Day 1-3 uncommitted diagnostic (converter + Format-A ingest
route) observed the following on 10,049 successfully-processed
sessions (7 errors from the multi-`trace_id` case §1.4 that this
amendment fixes). Bands below are set to encompass those diagnostic
observations plus a modest safety margin, giving the committed
adapter re-run room to move without triggering a §7 miss.

| ID | Prediction | Diagnostic anchor | Rationale |
|---|---|---:|---|
| **P1** | `union_wr_char ∈ [0.85, 0.999]` | 0.9233 | Chat-only accumulation drives high resend; band mirrors Corpus B [0.85, 0.999]. |
| **P2** | `union_wr_cost ∈ [0.85, 0.999]` | 0.9397 | Uncached tier → collapses to WR_char neighborhood (Corpus B P2 miss lesson). |
| **P3** | `SDR@10 ∈ [0.85, 1.00]` | 0.9332 | Chat-only sessions of any nontrivial length exceed 10% resend. |
| **P4** | `context_resend ≥ 99%` of union numerator | ~100% (structural) | Three other detectors are structurally zero (§1.5). |
| **P5** | Adapter fidelity: token invariant preserved on ≥ 99.5% of built sessions | 100% (10,049 / 10,049 diagnostic-ok) | The invariant `sum(input_tokens + output_tokens) == exgentic.total_tokens` per row. |
| **P6** | Adapter fidelity: multi-`trace_id` sessions no longer raise | 7 → 0 errors | §1.4 fix removes the diagnostic-converter error mode. |
| **P7** | Pricing warnings: zero `unknown model` warnings across the full re-scan | 0 (Cost Table Exgentic Expansion §9.4) | Cross-check with Rule 8 chain PR #102. |

**What would violate expectations (would trigger honest §10 note):**

- Any P1-P7 miss.
- Union numbers on Corpus C that materially diverge from the
  diagnostic beyond bootstrap CI. Direction of divergence must
  be documented.
- New failure modes surfaced by the committed adapter that the
  diagnostic did not see (e.g. schema drift between the two paths).

Meeting all predictions is not evidence of correctness — it is
consistent-with-expectation. Missing them triggers a §10 note but
does not invalidate the metric.

## 5. Method

1. Implement `src/clew/ingest/exgentic.py` per §1.
2. Unit tests in `tests/ingest/test_exgentic.py`:
   (a) attribute namespace bridge (each mapping line in §1.2 fires),
   (b) synthetic CHAIN root has null parent and envelope times,
   (c) multi-`trace_id` mode collapses to primary, tie-break rule
       is deterministic,
   (d) chat-only scope holds — non-chat spans (if any leak in) raise
       or are dropped by explicit rule,
   (e) cache-tier None fields propagate.
3. Full corpus scan using the committed adapter and the merged
   pricing table (`data/exgentic/*.parquet` shards 0-8, all 10,057
   sessions). Same seed convention as prior scans (`seed=42` where
   applicable).
4. Append the union numbers, per-session distribution, and P1-P7
   verdicts as §10 of this document.
5. Publish committed diagnostics: `field_test/diagnostics/exgentic_day5_committed_scan.py`
   uncommitted per `feedback_diagnostics_uncommitted`, but its
   `.RESULTS.json` is retained locally for reproducibility notes.

## 6. Explicit non-commitments

- Not committing to a rubric-v3 for chat-only LLM-judge. That is a
  separate follow-up (Day 3.5 diagnostic §9.11 of the LLM-judge
  Scale Expansion prereg).
- Not committing that all 6 benchmarks × 5 models × 5 harnesses
  produce comparable per-cell distributions. §10 will report
  per-benchmark and per-model breakdowns as observations, not
  claims.
- Not committing that the 0.07% multi-`trace_id` cases represent
  the actual production frequency of cross-trace agent structure.
  This is Exgentic-corpus-specific and post-filter.
- Not committing to a v2 that reconstructs the filtered-out
  `execute_tool` / `invoke_agent` spans. Chat-only is the corpus
  scope.

## 7. Commit chain (per `feedback_rule_8`)

Three commits, no squash/rebase:

1. `docs: Waste-rate Metric Exgentic Adapter Amendment prereg` —
   this file only. PR opened for approval.
2. **After approval:** `feat(ingest): Exgentic parquet adapter` —
   `src/clew/ingest/exgentic.py` + `tests/ingest/test_exgentic.py`.
3. `docs(waste_rate): append §10 Exgentic full-scan re-run` — new
   §10 in this file documenting the committed-adapter numbers and
   P1-P7 verdicts.

Follow-ups (not in this chain):

- **README refresh PR** — Corpus C row added to §Waste-rate metric
  table, 3-corpus pitch reflected.
- **LLM-judge Corpus C results** — Day 3.5 diagnostic on the v1
  rubric feeds into a separate follow-up prereg (rubric-v3 design
  if the v1 result confirms structural mismatch on chat-only).

## 8. Diagnostic scripts (uncommitted, referenced)

Not committed per `feedback_diagnostics_uncommitted`:

- `field_test/diagnostics/exgentic_convert_and_ingest.py` — Day 1
  first-session probe.
- `field_test/diagnostics/exgentic_day2_stratified_10.py` — Day 2
  stratified-10 benchmark.
- `field_test/diagnostics/exgentic_day3_full_scan.py` — Day 3
  full 10,056-session diagnostic; produced the anchors in §4.
- `field_test/diagnostics/exgentic_day3_anomaly_probe.py` — Day 3
  anomaly investigation (77 wr_char > 1.0 · 7 multi-trace_id · union
  vs mean).
- `field_test/diagnostics/exgentic_day3_5_llm_judge_300.py` — Day 3.5
  LLM-judge v1 rubric on Corpus C 290 stratified sessions
  (still running at prereg commit time).

## 9. Results — full-scan re-run (post-adapter)

*Placeholder. Populated by commit 3 above.*
