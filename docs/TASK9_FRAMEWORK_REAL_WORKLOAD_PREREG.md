# Task #9 · Framework Real Workload Collection — Pre-registration

**Status.** Pre-registration. Per `feedback_rule_8_pr_route`, this
document is pushed and PR-opened before any workload run or fixture
lands. Frozen positions below are pre-committed; adjusting them after
seeing results is not allowed.

## §0. Positioning · honesty preface

**Fact-based context:**

- Phase A (`field_test/diagnostics/task9_phaseA_detector_coverage.py`,
  2026-08-07) exercised our 3 deterministic detectors on 52 framework
  sub-traces (stub-based dumps in `framework_expansion_dumps/`).
- Ingest coverage: 43/52 = 82.7% (after multirun-split workaround).
- Detector output on stub data: **CR non-zero in 7 sub-traces**
  (haystack · pydantic_ai × 5 · strands_agents × 2); **PD/RR zero
  everywhere.** This matches the shape of the stub scenarios (no tool
  re-invocation, no Read calls).
- Direction B (SaaS product supporting non-CC frameworks) requires
  evidence that the detectors produce signal on **real workloads**,
  not just stubs.

**Scope frozen for this prereg:** collect real-workload traces from
Tier 1 frameworks (§5) under a single fixed scenario (§4), ingest via
our OpenInference adapter, run all 3 deterministic detectors + opt-in
LLM-judge, report per-detector signal counts and one Go/No-go verdict
per detector-framework cell.

**Out of scope for this prereg (deferred):**
- Empty-`output_text` Pydantic validator relaxation (9 sub-traces
  still failing Phase A ingest — separate amendment).
- Framework probe re-runs with different scenarios (this prereg
  freezes ONE scenario per framework for reproducibility).
- LLM-judge amendment further tuning (base + amendment v1 spec used
  as-is).
- Waste-rate metric (option C from `tomorrow_2026_08_07_start.md` —
  separate prereg).

## §1. Detection targets (unchanged from base preregs)

Detectors run on collected traces:

| Detector | Source spec | Frozen |
|---|---|---|
| Provable Duplicate (structural) | `docs/PROVABLE_DUPLICATE_*` (existing) | Yes |
| Context Resend | `docs/CONTEXT_RESEND_DETECTOR_PREREG.md` | Yes |
| Redundant Read | `docs/REDUNDANT_READ_DETECTOR_PREREG.md` | Yes |
| LLM-Judge Semantic Duplicate | `docs/LLM_JUDGE_SEMANTIC_DUPLICATE_PREREG.md` + `LLM_JUDGE_AMENDMENT_v1.md` | Yes |

No detector code is modified by this prereg. This prereg only
**collects data and reports counts.**

## §2. Frameworks · frozen list (Tier 1)

Per `docs/OPENINFERENCE_FRAMEWORK_EXPANSION_PREREG.md` §5.1:

| # | Framework | Instrumentation | Notes |
|---|---|---|---|
| T1.1 | **LlamaIndex** | Official OpenInference instrumentor | Popularity anchor |
| T1.2 | **OpenAI Agents SDK** | Official OpenInference instrumentor | 2025-2026 growth |
| T1.3 | **Anthropic SDK direct** | OpenInference wrap via helper (verified prior · `framework_probe_anthropic_wrapped.py`) | CC user adjacent |
| T1.4 | **AutoGen** | OpenInference instrumentor | Multi-agent, pingpong candidate |

**No Tier 2 in this prereg.** Tier 2 (Pydantic AI, Google GenAI,
Haystack, Smolagents, MCP) is a follow-up prereg based on Tier 1
results.

**Order:** T1.1 → T1.2 → T1.3 → T1.4 sequentially. Stop early only
on API budget exhaustion (§7), not on PASS count.

## §3. Success criteria (frozen · per detector-framework cell)

For each (framework, detector) cell:

- **PASS** — detector returns ≥ 1 non-empty event on that framework's
  trace, AND no crash.
- **FAIL** — detector crashes with exception.
- **EMPTY** — detector returns 0 events, no crash. Reported as-is
  (framework/scenario did not trigger; not a detector defect).

**Overall Task #9 Go/No-go (frozen):**

- **GO** — ≥ 3 of 4 Tier 1 frameworks show at least ONE non-empty
  detector cell across the 4 detectors (i.e., pipeline demonstrably
  produces waste signal on non-CC data). Justifies Direction B
  "framework support" claim in pitch/marketing.
- **NO-GO** — 0 or 1 Tier 1 framework shows any non-empty cell.
  Framework-support claim not defensible from current scenarios; need
  scenario redesign or wait for Phase C (Tier 2 + more scenarios).
- **MIXED (2 of 4)** — ship as-is, document which frameworks work.
  Marketing narrows to "works on frameworks A and B" without claiming
  general coverage.

**Non-commitment:** these thresholds are chosen conservatively BEFORE
running any workload. Post-hoc re-interpretation is not allowed.

## §4. Workload scenario (frozen · one per framework)

**Scenario name:** "Coding-task retry loop"

**Description:** the agent is asked to accomplish a small coding task
(implement a function meeting a spec + test), receives a failing
test result on the first attempt, and retries with a fix. This
scenario is chosen because:

1. Small, cheap to run under budget cap.
2. Exercises tool re-invocation (edit + run same test twice → PD/RR
   candidates).
3. Exercises context accumulation (retry loop keeps prior turns →
   CR candidates).
4. Exercises semantic paraphrase (agent may re-explain its plan in
   different words → LLM-judge candidates).

**Concrete task (frozen wording):**

> "Write a Python function `fizzbuzz(n)` that returns 'Fizz' for
> multiples of 3, 'Buzz' for multiples of 5, 'FizzBuzz' for
> multiples of 15, and str(n) otherwise. Save it in `fizzbuzz.py`.
> Then run `python -c \"from fizzbuzz import fizzbuzz; assert
> fizzbuzz(15) == 'FizzBuzz'\"` to verify. If verification fails,
> fix the function and retry."

The scenario is fixed to keep runs comparable across frameworks.

**Deliberate imperfection seed:** the agent's initial prompt is
underspecified enough that ~30-50% of runs are expected to require at
least one retry (based on model calibration norms — not measured
here; a background assumption, not a Go/No-go criterion).

## §5. Resource limits (frozen)

- **API budget cap (total, hard):** $10.00 across all 4 frameworks.
- **Per-framework cap:** $2.50 (allows 4 frameworks under total cap
  with headroom).
- **Turn cap per run:** 15 turns (LLM messages). Abort past this.
- **Wall-clock cap per framework:** 30 minutes (setup + run + trace
  export). Abort if exceeded.
- **Model selection:** each framework uses `claude-sonnet-4-5`
  (Anthropic) for consistency. Justification: this is the model our
  own CC session uses; comparable pricing baseline; well-supported by
  all Tier 1 frameworks.

**Rationale for these limits:** Phase B is a validation run, not a
scaling exercise. Small deterministic workload is enough to prove
detectors return signal on real (non-stub) traces.

## §6. Method

For each framework in T1.1-T1.4 order:

1. **Setup**
   - Install framework + OpenInference instrumentor (versions pinned
     at run time; recorded in results doc).
   - Configure OpenInference to export via `InMemorySpanExporter` (or
     equivalent) to a file `field_test/diagnostics/task9_phaseB_<framework>.json`.

2. **Run**
   - Execute the §4 scenario ONCE with the chosen model.
   - Capture per-turn token counts, tool calls, and full context.
   - Turn cap and cost cap enforced (§5).

3. **Ingest**
   - Load the export via `ingest_from_otel_json` (fallback: OpenInference).
   - If ingest fails, record failure mode and move to next framework
     (do not modify ingest code — that's a separate amendment).

4. **Detectors**
   - Run PD (`find_repeat_candidates` + `cascade` if embedder OK, else
     `find_repeat_candidates` alone as PD proxy).
   - Run `find_context_resend`.
   - Run `find_redundant_reads`.
   - Run `find_llm_judge_semantic_duplicates` (opt-in flag set for
     this run; API budget accounted against §5 cap).

5. **Record**
   - Per-detector event count.
   - Per-detector crash (if any).
   - Per-framework total cost consumed.
   - Trace export file path (kept locally, not committed per rule
     "diagnostics uncommitted").

## §7. Reporting

**Uncommitted diagnostic artifacts** (per rule 8 step 3):

- `field_test/diagnostics/task9_phaseB_<framework>.json` — raw trace
  export per framework.
- `field_test/diagnostics/task9_phaseB_detector_results.RESULTS.json` —
  aggregate results.
- `field_test/diagnostics/task9_phaseB_detector_results.md` — human
  summary.

**Committed to this prereg** (§8 amendment after run):

- Per-cell PASS/FAIL/EMPTY grid (4×4 = 16 cells).
- Overall Go/No-go verdict.
- Total API cost consumed.
- Setup notes (installation quirks per framework).

## §8. Backout plan

Same as base preregs. This prereg **does not modify production code**.
It creates diagnostic artifacts and appends results to this document.
No revert needed. Discovered ingest bugs are logged for a future
amendment.

## §9. Commit chain (per feedback_rule_8)

1. **This prereg** — pushed on its own branch, PR opened, URL returned
   to user. STOP for approval.
2. On approval: execution (single Python script + results docs
   appended to this file § "Results"). Diagnostic files remain
   uncommitted per rule 8 step 3.
3. If results warrant follow-up (e.g., PASS on all 4 → memory update
   confirming Direction B; NO-GO → memory update noting current
   scenario insufficient), that's a separate memory commit, not a
   code PR.

## §10. Explicit non-commitments

- No claim that all 4 Tier 1 frameworks will PASS. Outcome is what
  it is.
- No claim about detector event volume being high or "matches"
  competitive with CC 98.5% baseline. Framework signal may be small
  by construction (single-scenario, short workload).
- No claim about pricing/cost comparability across frameworks. Model
  is fixed (Anthropic Sonnet 4.5); framework-side overhead varies.
- No claim about waste-rate percentages (%tokens wasted). §12-style
  ratio metric is out of scope; that lives in a follow-up prereg
  (waste-rate metric).
- No claim about resolving the 9 Phase A ingest failures. Empty
  `output_text` Pydantic tolerance is a separate amendment.

## §11. Explicit non-changes

The following remain untouched by this prereg:

- Base prereg specs (CONTEXT_RESEND, REDUNDANT_READ, LLM_JUDGE +
  amendment) — unchanged.
- Frozen ingest validator behavior (empty output_text rejection).
- Frozen model selection defaults.
- Frozen tests.

Only new file added: this prereg itself.
