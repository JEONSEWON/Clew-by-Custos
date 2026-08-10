# Waste-rate Metric — Pre-registration

**Status.** Pre-registration. Per `feedback_rule_8`, this document is
pushed and PR-opened before any measurement script or reporting code
lands. Metric definitions, corpora, detector set, and session
threshold below are the pre-committed frozen positions; adjusting them
after seeing results is not allowed.

## 0. Honesty preface (what this measurement is and is not)

The Clew repo already emits per-detector numbers (Context Resend
aggregate 98.5% on CC, LLM-judge post-amendment 52.20% on 5 CC
sessions, cascade waste cost ranges $0-$6.40 per CC session,
Toolathlon 4,249 provable-duplicate pairs at 2.41% of tool spans).
Each is defensible on its own terms. What is missing is a **single
"session-level waste rate" number** that answers, in one line:

> "Across our measured corpora, Clew flags waste on M% of sessions,
> with a median WR_char of N% per session."

Sales-facing material needs this number; individual detector
percentages don't compose cleanly (Context Resend on input tokens vs.
provable duplicate on tool spans vs. redundant read on file bytes are
different denominators). This prereg specifies **three metrics** to
report per-corpus per-detector, plus a **union metric** and a
**session-detection rate** at a fixed threshold. All five detectors
are unchanged; this is a measurement + reporting layer.

**Not claimed by this prereg:**

- That the union metric is the "true" waste rate. It's an upper
  bound; detector overlap and per-detector precision limits are
  documented in §10.
- That trace-commons and Toolathlon reflect "typical production
  usage". Both are convenience samples of publicly available traces.
- That any particular value of any metric will be pitch-friendly. The
  measurement is the question, not the answer.

## 1. Metric definitions (frozen)

Three metrics reported per (corpus, detector) cell, plus the same
three computed on the union across detectors.

### 1.1 Char-based waste ratio (WR_char)

For a single trace:

```
WR_char =
    sum(len(span.output_text.encode("utf-8")) for span in waste_spans)
  / sum(len(llm_call.input_text.encode("utf-8")) for llm_call in trace.llm_calls)
```

Rationale: pure UTF-8 byte count. No pricing dependency, no
tokenizer dependency. Reproducible across dataset ages and provider
pricing changes. Numerator is what the detector flags as wasted
output; denominator is total input the trace sent to any LLM call.

If `trace.llm_calls` is empty (Trace has no LLM span with
`input_text`) then WR_char is `None` for that trace and it is
excluded from the corpus aggregate (with an explicit count of
excluded traces reported).

### 1.2 Cost-based waste ratio (WR_cost)

For a single trace:

```
WR_cost =
    sum(span.waste_cost for span in waste_spans)
  / trace.total_input_cost
```

Uses existing cost attribution (per
`docs/COST_ATTRIBUTION_COMPLETION_PREREG.md`). `waste_cost` is
detector-attributed; the union rule (§4.2) tie-breaks by
first-flagging detector to avoid double-counting.

If `trace.total_input_cost` is 0 or the trace has no `cost_accuracy_flag`
set (unpriced model) then WR_cost is `None` and the trace is excluded
from the WR_cost aggregate (again with explicit count).

### 1.3 Session detection rate at 10% (SDR@10)

For a corpus:

```
SDR@10 = |{ trace ∈ corpus : trace.WR_char ≥ 0.10 }| / |corpus|
```

Applied to per-detector WR_char and to union WR_char, per corpus.

## 2. Corpus (frozen)

### 2.1 Corpus A · trace-commons (Claude Code)

- **Source:** `data/hf_recon/trace_commons_paths.txt`
- **Selection:** all 28 sessions (no sampling — this is the observed
  corpus size, matching `docs/CONTEXT_RESEND_DETECTOR_PREREG.md` §7
  precedent).
- **Order:** file order in `trace_commons_paths.txt`, deterministic.
- **Manifest sha256:** computed as
  `sha256(newline-joined sorted absolute paths).hexdigest()` and
  recorded in the results artifact.

### 2.2 Corpus B · Toolathlon

- **Source:** `data/toolathlon/hf/*.jsonl`
- **Selection:** all trajectories present (approximately 6,780 per
  Toolathlon paper; exact count recorded at scan time).
- **Order:** alphabetical file order.
- **Manifest sha256:** same rule as Corpus A.

Both corpora are frozen at prereg-push time. Any file added or
removed after that requires a documented amendment before re-run.

## 3. Detector set (frozen)

**Included in waste_spans aggregation** (four deterministic
detectors):

| # | Detector | Symbol | Emitted spans counted |
|---|---|---|---|
| 1 | Repeat (cascade) | `find_repeat_candidates` + cascade | `WasteResult.waste_spans` (post-error-gate, post-idempotent-classification per current cascade output) |
| 2 | Context Resend | `find_context_resend` | `ContextResendResult.resent_events`; each event contributes its origin chunk bytes |
| 3 | Redundant Read | `find_redundant_reads` | `RedundantReadResult.events`; both `confirmed=True` and `confirmed=False` counted (per `docs/REDUNDANT_READ_DETECTOR_PREREG.md` §1) |
| 4 | Duplicate creation check | id-bridge scan | pairs with `differing_entity_id` (per `docs/ID_BRIDGE_PRODUCTION_PREREG.md` §1.8). `same_entity_id` and `no_id` are NOT counted here (they are audit signals, not proven waste) |

**Explicitly EXCLUDED:**

- `find_llm_judge_semantic_duplicates` — opt-in, cost-gated, not
  part of the default pipeline. Its 0.5220 detector precision
  (LLM_JUDGE_AMENDMENT_v1) does not translate to a byte- or cost-
  ratio without further specification.
- `find_pingpong_candidates` — code path exists but has fired only
  on synthetic traces; no external corpus evidence
  (`project_pingpong_blocked.md`).

Detector order for union tie-breaking (§4.2) is **frozen**:
`[repeat, context_resend, redundant_read, duplicate_creation]`.

## 4. Aggregation rule (frozen)

### 4.1 Per-detector metrics

For each `(corpus, detector)` cell: compute WR_char, WR_cost,
SDR@10 independently. This yields:

- Per corpus: 4 detectors × 3 metrics = **12 numbers**
- Reported for both Corpus A and Corpus B → **24 numbers total**

### 4.2 Union metric

Applied per trace:

1. Collect the set of `span_id`s flagged by any of the four detectors
   for this trace. Each `span_id` is unique in the trace by
   construction.
2. **Byte-uniqueness:** each `span_id` in the union contributes its
   `output_text` bytes to `union_WR_char` numerator exactly once,
   regardless of how many detectors flagged it.
3. **Cost tie-break:** for `union_WR_cost`, if `span_id` was flagged
   by multiple detectors, its `waste_cost` is attributed to the FIRST
   detector in the frozen order (§3). Deterministic.
4. `union_SDR@10` = fraction of traces with `union_WR_char ≥ 0.10`.

Chunk-level detectors (Context Resend) don't emit `span_id` per
chunk — they emit `chunk_hash` inside an `llm_span_id`. For union
purposes, a chunk contributes bytes independently (chunks don't
collide with tool-span byte counts because they come from different
denominators — the union is over the *set of flagged units*, tool
spans and chunks kept in separate buckets, aggregated at the end).

**Byte accounting caveat (pre-committed):** if a tool `Read` span
appears in both `repeat` (cascade) and `redundant_read` outputs
with the same `span_id`, its bytes count once for `union_WR_char`.
If a chunk in `context_resend` happens to be a serialization of the
same tool result, it is NOT deduplicated across the two categories
(tool-span bytes ≠ chunk bytes by construction). This is honestly a
simplification; a v2 would need cross-category dedup. Flagged for
future amendment, not blocking v1.

### 4.3 Per-corpus aggregation

For each corpus, aggregate over included traces:

- `agg_WR_char` = sum(numerator) / sum(denominator) across traces (weighted-ratio, not mean of ratios).
- `agg_WR_cost` = same, over cost.
- `SDR@10` = count / total, unweighted.

95% bootstrap CI on `agg_WR_char` (weighted-ratio bootstrap over
per-trace pairs, `n_boot=1000, seed=42`) per corpus per detector and
for union.

## 5. Session detection threshold (frozen)

`WR_char ≥ 0.10` (10%) defines "session has waste" for SDR.

**Rationale for the specific value:**

- 5% is close to trace-to-trace noise variance observed in
  provable-duplicate corpora (~0.80% CC baseline, 2.41% Toolathlon).
- 20% is the Context Resend §7 hero threshold — trivially triggered
  by all CC sessions (~98.5% aggregate), which makes SDR@20 a
  degenerate "100% for Corpus A" metric with no discriminative power.
- 10% is a compromise between these, chosen without calibration on
  labeled data (none exists at session-level waste). This is
  documented arbitrariness — the number is fixed here to prevent
  post-hoc tuning after results.

**Pre-committed prediction:** for Corpus A (CC), `context_resend`
alone triggers ≥ 10% on essentially every session, so per-detector
SDR@10 for context_resend on Corpus A will be near 1.0 and
`union_SDR@10` will match. This is not a failure of the metric —
it's a truthful reading of the CC waste distribution. Corpus B
(Toolathlon) is where SDR is expected to carry discriminative
information.

## 6. Method

For each corpus × trace:

1. **Ingest** via existing adapter (auto-detect format; no adapter
   changes required for this prereg).
2. **Run all 4 detectors** deterministically in the frozen order.
   Detector code is unchanged by this prereg.
3. **Collect waste_spans** per detector into `per_detector[i]`.
4. **Compute WR_char, WR_cost** per detector.
5. **Compute union** per §4.2.
6. **Emit** per-trace metrics record.

Then aggregate per corpus per §4.3.

**No new detector code. No pricing table changes. No test suite
changes.** This prereg introduces:

- One measurement script:
  `field_test/diagnostics/waste_rate_metric.py` (uncommitted, per
  rule 8 step 3).
- Optionally, new numeric fields on the JSON report output
  (`--json`) surfacing per-trace WR_char, WR_cost. Markdown report
  gets a one-line summary "Waste rate on this trace: X% of input
  bytes flagged as waste (union of 4 detectors)". Details of report
  integration are §6.1 below.

### 6.1 Report integration (frozen scope)

Optional, and only if implementation stays under ~50 LoC of report
model changes. Otherwise deferred to a follow-up prereg.

- New optional field on `TraceReport` (JSON): `waste_rate` object
  with subfields `{ wr_char, wr_cost, per_detector: {...} }`.
- Markdown report: one-line addition to "Result" section.
- If either implementation exceeds 50 LoC, split into a separate
  prereg. This prereg's implementation commit stays measurement-only
  in that case, and the report integration becomes a follow-up.

## 7. Test plan

### 7.1 Unit tests (`tests/metrics/test_waste_rate.py`, new file)

Fixtures use hand-constructed `Trace` objects with LLM inputs and
tool-span outputs populated to exercise each metric arithmetic.

1. `test_wr_char_single_detector_repeat` — trace with one flagged
   repeat pair (span sizes known); WR_char equals expected fraction.
2. `test_wr_char_multiple_detectors_no_overlap` — two detectors flag
   different spans; per-detector metrics correct; union sums both.
3. `test_wr_char_multiple_detectors_with_overlap` — same span
   flagged by both `repeat` and `redundant_read`; per-detector
   metrics count it once each; union counts it once (byte-unique).
4. `test_wr_cost_uses_frozen_tie_break_order` — same span flagged by
   `repeat` and `redundant_read`; `union_WR_cost` attributes to
   `repeat` (first in frozen order).
5. `test_wr_char_empty_llm_calls_returns_none` — trace with no LLM
   spans → WR_char is `None`, trace excluded from corpus aggregate.
6. `test_wr_cost_unpriced_model_returns_none` — trace with LLM spans
   but no cost attribution → WR_cost is `None`.
7. `test_sdr_at_10_threshold_boundary` — trace with WR_char =
   0.0999 excluded from SDR@10 numerator; 0.1000 included.
8. `test_deterministic_repeat_produces_identical_record` — running
   metric twice on same trace produces byte-identical JSON output.
9. `test_context_resend_chunk_bytes_do_not_dedup_against_tool_bytes`
   — pre-committed simplification of §4.2 caveat; explicit test.

### 7.2 Existing test suite

All 548 existing tests must remain green. No test modifications.

## 8. Go/No-go (frozen)

**This prereg has no Go/No-go verdict.** It is a **measurement-only
prereg**: the aggregate numbers are reported as-is, and pitch/
marketing decisions about which metric(s) to use are made
downstream, in a separate session, informed by the numbers.

The rationale for no Go/No-go: each included detector already went
through its own Go/No-go under its own prereg. Bundling them into a
unified metric does not create new statistical claims — it just
gives sales a compact way to summarize what the detectors already
found.

## 9. Backout plan

This prereg does not modify production detection code. Backout =
revert the measurement script + optional report-model additions +
the results-amendment commit. No data migration; no user-visible
API surface change other than the new `waste_rate` field (marked
optional, additive).

## 10. Explicit non-commitments

- No claim that any metric will be above or below any particular
  value.
- No claim that the union metric is the "true" session waste rate.
  Overlap between detectors and per-detector precision limits mean
  the union is an upper bound; per-detector precision on labeled
  data is only known for `repeat` (RedundancyBench P=0.826, README
  §Where it stands).
- No claim that trace-commons or Toolathlon reflect "typical
  production usage". Both are convenience samples.
- No claim that Toolathlon per-model variation reflects model
  quality (task-mix confounds uncontrolled — see README Toolathlon
  subsection).
- No claim about LLM-judge inclusion in future versions. That is a
  separate prereg.
- No claim about the 10% SDR threshold being "correct". §5
  documents its arbitrariness explicitly.

## 11. Explicit non-changes

The following remain untouched by this prereg:

- All frozen detector parameters (φ, N, embedding model,
  `_READ_TOOLS`, `_ID_BRIDGE_MAPPING`, etc.).
- All frozen tests.
- Report JSON schema (this prereg adds one optional field
  `waste_rate`; existing fields unchanged).
- LLM-judge opt-in gate.
- Cost attribution pricing tables (this prereg consumes them, does
  not modify them).
- Corpus contents (trace-commons file list, Toolathlon corpus).

## 12. Commit chain (per feedback_rule_8)

1. **This prereg** — pushed as its own commit on new branch,
   PR opened, URL returned to user. STOP for approval.
2. On approval: measurement script + tests (`field_test/diagnostics/
   waste_rate_metric.py` uncommitted; `tests/metrics/
   test_waste_rate.py` and `src/clew/metrics/waste_rate.py`
   committed). Single or two commits.
3. Optional: report-model integration if under §6.1 LoC budget.
   Separate commit.
4. Corpus scan + results append to this file § "Results" (below).
   Diagnostic RESULTS artifacts uncommitted per rule 8 step 3.

No squash, no rebase. Commit chain preserved.

## 13. Results (Corpus A executed 2026-08-10; Corpus B deferred)

Rule 8 step 2 — execution results appended after run. Numbers below
are the record of record.

### 13.1 Corpus A · trace-commons (28 CC sessions)

- **Manifest sha256:** `be511bcd6ce0e1a72ae794dc06105033331f21a55123bd15eb9c77ab20494e1a`
- **Traces:** 28 total, 28 included (0 excluded)
- **Elapsed:** 1193s (~20 min single-threaded) on Windows 11, torch
  2.6.0+cu124, embedder `paraphrase-multilingual-MiniLM-L12-v2 @
  e8f8c211226b894fcb81acc59f3b34ba3efd5f42`.

#### 13.1.1 Per-detector metrics (Corpus A)

| Detector | WR_char | WR_cost | SDR@10 |
|---|---:|---:|---:|
| `repeat` (cascade) | 0.0000 | 0.0000 | 0.0000 |
| `context_resend` | **0.9930** | **0.2903** | **0.9643** |
| `redundant_read` | 0.0000 | 0.0000 | 0.0000 |
| `duplicate_creation` | 0.0000 | 0.0000 | 0.0000 |

#### 13.1.2 Union metrics (Corpus A)

| Metric | Value |
|---|---:|
| `union_wr_char` | **0.9930** |
| `union_wr_cost` | **0.2903** |
| `union_sdr_at_10` | **0.9643** (27 of 28 sessions) |

#### 13.1.3 Bootstrap 95% CI on `union_wr_char`

`n_boot=1000, seed=42`, weighted-ratio bootstrap over per-trace `(union_waste_bytes, total_input_bytes)`:

- **lower_2_5:** 0.9892
- **median:** 0.9929
- **upper_97_5:** 0.9944

#### 13.1.4 Per-trace WR_char distribution

- **n:** 28
- **min / max:** 0.0000 / 0.9954
- **median:** 0.9835
- **p10 / p90:** 0.7971 / 0.9940
- **count ≥ 0.10 (SDR@10 numerator):** 27 / 28

### 13.2 Corpus B · Toolathlon (deferred)

- **Manifest sha256:** `9648d18876685ae54ee20abcb88e191f0914f20f2025ff38a9d2cedb0699d4f7`
- **Files:** 66 JSONL (each containing multiple trajectories per Toolathlon `model_run` structure; approximately 6,780 total trajectories per the paper).
- **Status:** **Not scanned in this pass.** Per-trajectory cascade with the frozen embedder averaged ~40s per session on Corpus A; extrapolating to ~6,780 trajectories gives an estimated wall-clock of many hours to a day, which was not feasible in the session that produced this results append.
- **Deferral policy:** the Corpus B scan is deferred to a follow-up run using the same frozen `waste_rate_metric.py` script with `SCAN_TOOLATHLON=True`. When completed, results will be added as §13.5 in a subsequent PR referencing this prereg. **No metric definitions, corpus manifests, detector set, or thresholds are changed by this deferral** — the frozen positions (§1-5) remain the same for the Corpus B pass.

### 13.3 Interpretation (matching §5 predictions)

**Predictions from §5 that were verified:**

- §5 predicted "`context_resend` alone triggers ≥ 10% on essentially every session, so per-detector SDR@10 for `context_resend` on Corpus A will be near 1.0 and `union_SDR@10` will match." — **verified:** `context_resend_sdr_at_10 = 0.9643`, `union_sdr_at_10 = 0.9643`; the one session that fell below 10% (`4c09dfa9` with WR_char = 0.0000) is a no-tool-use session that the CC adapter recovered as a root-only Trace, contributing no LLM input bytes flagged as waste.
- §5 predicted the metric on Corpus A would be dominated by `context_resend`. — **verified:** the other three detectors returned 0 across all 28 sessions. Provable Duplicate (cascade) requires byte-exact tool output AND no compact-boundary gap AND no state change; Redundant Read requires an interval-clean gate that CC's iterative edit workflow often breaks; Duplicate Creation (id-bridge) requires side-effect tools like `canvas-*` / `notion-*` that appear in Toolathlon but not in these CC sessions.

**A finding not pre-committed but worth noting:**

- `union_wr_char = 0.9930` and `union_wr_cost = 0.2903` **diverge by 3×**. This is expected under the current cost model: WR_char counts UTF-8 bytes uniformly, while WR_cost apportions provider-reported input tokens per-chunk (proportionally by tiktoken length) — chunks that are short but repeat many times contribute a small cost share each time even though they contribute a large char share cumulatively. The two ratios answer different questions and neither is wrong. Pitch material that uses the "%" without qualifier should say which one (`char` is more conservative for "how much of the trace is waste"; `cost` is more accurate for "how much of your bill is waste").

### 13.4 Notes on the scan

- The measurement script `field_test/diagnostics/waste_rate_metric.py` remains uncommitted per rule 8 step 3.
- Raw per-trace results in `field_test/diagnostics/waste_rate_metric.RESULTS.json` (uncommitted). Manifest sha256 in §13.1 above suffices for reproducibility given a fixed corpus.
- `PYTHONUNBUFFERED=1` was required to see live progress on Windows; a first run with buffered stdout succeeded silently until reaching a slow session. Documented for reproducibility.

### 13.5 Corpus B results

*(To be appended in a follow-up PR after the Toolathlon scan completes.)*
