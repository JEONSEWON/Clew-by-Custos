# LLM-as-Judge · Semantic Duplicate — Pre-registration

**Status.** Pre-registration. Per `feedback_rule_8`, this document is
pushed and PR-opened before any production code change lands. Frozen
positions below are pre-committed; adjusting them after seeing
implementation results is not allowed.

## 0. Positioning · honesty preface

**Fact-based context (all verified against 2026-08 vendor sources):**

- Industry standard for LLM evaluation platforms is **hybrid**:
  deterministic checks for structural/format, LLM-judge for subjective
  / open-ended.
  Sources: braintrust.dev/articles/what-is-llm-as-a-judge (2026-08),
  arize.com/guides/llm-as-a-judge (2026-08),
  futureagi.com/blog/why-llm-as-a-judge-2026 (2026-08).

- Existing waste-detection metrics offered by competitors are all
  LLM-judge based:
  - DeepEval `StepEfficiencyMetric` (`deepeval.com/guides/guides-ai-agent-evaluation-metrics`)
  - Confident AI Redundant Tool Calls, Tool Frequency, Convoluted Routes
    (`confident-ai.com/blog/llm-agent-evaluation-complete-guide`)

- Documented LLM-judge failure modes (all vendors agree):
  position bias (10-15%p winrate swing), verbosity bias, self-preference
  (10-25% bias toward same model family), calibration drift across
  model versions, cost 50-500× a classifier.
  Source: futureagi.com/blog/why-llm-as-a-judge-2026.

**Clew's positioning:**

- Deterministic detectors (`provable_duplicate`, `context_resend`,
  `redundant_read`) are our differentiator. They ship as pre-built
  rules — competitors require users to author scorers.
- **The gap they leave**: paraphrased re-sends. Two chunks with
  different bytes but the same meaning are missed by sha256.
- Adding a bounded LLM-judge layer for **semantic duplicate** extends
  the context_resend hero into paraphrase territory **without**
  compromising the determinism story of the base detectors.

**Scope frozen for v1 (this prereg):** semantic duplicate ONLY.
Other LLM-judge axes (hallucination, tone, helpfulness, silent
failure detection) are explicitly deferred to future preregs (§9).

## 1. Detection definition

A **semantic duplicate event** is emitted when:

1. Two message chunks `A` and `B` appear in the input of two distinct
   LLM calls within the same trace.
2. `sha256(A) != sha256(B)` (so `context_resend` did NOT flag this
   pair). Byte-exact matches remain the deterministic detector's
   territory.
3. A judge LLM, given both chunks under the frozen rubric (§4),
   returns `equivalent=true` with `confidence >= threshold` (§4).
4. The chunk role is NOT `"system"` (§1.2 of Context Resend prereg
   inherited).

When all four hold, occurrence of `B` is flagged as a semantic-resend
of `A`. The earliest-occurring chunk is treated as the origin.

## 2. Opt-in gate (default OFF)

**LLM-judge is DISABLED by default.** Users explicitly enable via
either:

- Environment variable `CLEW_ENABLE_LLM_JUDGE=1`
- CLI flag `--llm-judge`

**Rationale**: judge calls cost real money and introduce
non-determinism. Default OFF preserves existing user experience.

**When enabled but API key missing** (`ANTHROPIC_API_KEY` not set):
detector emits a warning and returns an empty result. Does not raise.

## 3. Judge model

**Default judge model:** `claude-haiku-4-5`.

Rationale: cheap ($1/M input, $5/M output per pricing.py) and
sufficient for equivalence judgment. Frozen default v1; users can
override via `CLEW_LLM_JUDGE_MODEL` env var.

**Provider:** Anthropic only in v1. OpenAI/Google support is a
future prereg concern.

**Determinism knobs (best-effort, still non-deterministic):**
- `temperature=0.0`
- `top_p=1.0`
- No streaming (full JSON response)
- Model version pinned via full model string (e.g.
  `claude-haiku-4-5` — no `-latest` suffix)

**Non-determinism policy (frozen):** even with `temperature=0.0`,
LLM outputs are NOT bit-reproducible across runs. The result carries
`cost_accuracy_flag = "estimated"` and the report explicitly flags
that judge-derived matches are non-reproducible.

## 4. Rubric (frozen prompt template)

The judge prompt is source-controlled in
`src/clew/detect/llm_judge/prompts.py` and MUST be treated as a
frozen artifact. Changing the prompt requires a new prereg.

**Template shape (frozen):**

```
System:
You are a strict equivalence judge for LLM message chunks. Two chunks
are "equivalent" only if they express the same request, tool call, or
information to the LLM. Formatting differences (whitespace,
punctuation, quotation style) are equivalent. Different content,
values, or intent are NOT equivalent.

User:
Chunk A:
<chunk A verbatim, truncated to 4000 chars>

Chunk B:
<chunk B verbatim, truncated to 4000 chars>

Return a JSON object:
{"equivalent": <true|false>, "confidence": <0.0-1.0>,
 "reasoning": "<one-sentence reason>"}
```

**Confidence threshold (frozen):** matches with `confidence >= 0.85`
are counted. Below that, treated as non-match (conservative).

**Chunk truncation (frozen):** each chunk truncated to 4000 chars
before sending. Longer chunks are compared by their heads. Full-chunk
comparison would blow token budget on long prompts.

**Output parsing (frozen):**
- Response MUST be valid JSON. Parse failure → count as non-match,
  log warning.
- Missing `equivalent` field → non-match.
- `confidence` not in [0.0, 1.0] → clamp to bounds.

## 5. Candidate selection

Running the judge on every unmatched chunk pair is prohibitively
expensive (N² judge calls). Candidate filtering:

**Stage 1 — Cheap pre-filter (deterministic):**

For each pair of unmatched chunks (A, B), compute Jaccard similarity
on character 3-grams:
```
jaccard(A, B) = |A_3grams ∩ B_3grams| / |A_3grams ∪ B_3grams|
```

Only pairs with `jaccard >= 0.30` are sent to the judge. Rationale:
completely different chunks (jaccard < 0.30) are extremely unlikely
to be semantic duplicates; skipping them saves 90%+ of judge calls
in typical workloads.

**Stage 2 — LLM judge (rate-limited):**

Filtered candidates are sent to the judge, capped at
`CLEW_LLM_JUDGE_MAX_CALLS` (default: 50, hard cap: 500).

**Determinism of candidate selection:** Jaccard similarity is
deterministic. Same trace → same candidate list. Only the judge
verdict is non-deterministic.

**Cost estimate before running:** the detector emits an estimated
maximum cost line to stderr before making the first judge call:

```
clew: LLM judge enabled — up to N candidate pairs, est. max cost $X.XX
```

User can interrupt (Ctrl+C) if the estimate is unacceptable.

## 6. Detector interface

New module: `src/clew/detect/llm_judge/` (package).

- `src/clew/detect/llm_judge/__init__.py`
- `src/clew/detect/llm_judge/prompts.py` (frozen rubric template)
- `src/clew/detect/llm_judge/anthropic_client.py` (thin wrapper)
- `src/clew/detect/llm_judge/semantic_duplicate.py` (this feature)

**Result dataclasses:**

```python
@dataclass
class LLMJudgeMatch:
    kind: Literal["semantic_duplicate"]
    chunk_a_hash: str
    chunk_b_hash: str
    origin_llm_span_id: str
    candidate_llm_span_id: str
    equivalent: bool
    confidence: float
    reasoning: str
    judge_model: str
    judge_cost: float

@dataclass
class LLMJudgeResult:
    trace_id: str
    matches: list[LLMJudgeMatch] = field(default_factory=list)
    total_judge_calls: int = 0
    total_judge_cost: float = 0.0
    total_semantic_resent_tokens: int = 0
    total_semantic_resent_cost: float = 0.0
    enabled: bool = False  # True iff user opted in AND API key present

def find_llm_judge_semantic_duplicates(
    trace: Trace,
    context_resend_result: "ContextResendResult",
    *,
    enabled: bool = False,
    judge_model: str = "claude-haiku-4-5",
    max_calls: int = 50,
) -> LLMJudgeResult: ...
```

**Cost attribution of semantic matches:** each match's
`total_semantic_resent_tokens` counted as the tokenized length of the
candidate chunk (same convention as Context Resend). Uses the
downstream LLM call's tier-aware rate (per Cost Attribution
Completion prereg §4).

## 7. Report integration

**Cost summary breakdown (Cost Attribution Completion prereg §5):**
- New line `detector_breakdown["semantic_duplicate"]` when the
  detector ran and produced non-zero matches.
- `TraceCostSummary.accuracy_flag` downgrades to `"estimated"` when
  ANY LLM-judge match contributed.

**Markdown:**
- New `## Semantic duplicates (LLM judge)` section below Redundant
  reads.
- Renders match count, judge calls, judge cost, top-5 offenders with
  reasoning.
- Section omitted when detector was disabled or produced no matches.
- Header footnote: "Judge model: {model} · judge cost: ${cost} ·
  Results non-reproducible (LLM-as-judge)"

**JSON:**
- New top-level `llm_judge` block with the full result.
- `None` when disabled or when result has no matches.

**Backward compat:** all new parameters default to disabled/None.
Existing callers get byte-identical output.

## 8. Rate limits and safety rails

- **Hard cap per trace**: 500 judge calls, regardless of user
  `CLEW_LLM_JUDGE_MAX_CALLS` setting. Prevents runaway costs on
  pathological traces.
- **Anthropic API rate limits**: respect `Retry-After` header on 429.
  Backoff with exponential (initial 1s, max 32s).
- **Timeout per call**: 30 seconds. Timeout → log warning, count as
  non-match, continue.
- **Total cost cap**: env var `CLEW_LLM_JUDGE_MAX_COST_USD` (default:
  10.0). Stop making judge calls once accumulated cost exceeds this.

## 9. Explicitly out of scope for v1

Following LLM-judge axes are **deferred to future preregs**, one
prereg per axis:

- **Silent failure detection** — tool returned success status but
  content is empty/nonsense.
- **Hallucination detection** — LLM output contradicts tool response.
- **Tone / helpfulness** — quality axes (Braintrust / Arize territory).
- **Convoluted route** — DeepEval-style trajectory efficiency.
- **Multi-judge ensemble** — same call to 2+ models, majority vote.
- **Judge model auto-recalibration** — drift detection across model
  versions.
- **Non-Anthropic providers** — OpenAI, Google, local models.

These belong on the roadmap but are not this prereg's concern.

## 10. Determinism policy (summary)

| Component | Deterministic? | Notes |
|---|---|---|
| Candidate selection (Jaccard) | Yes | Same trace → same candidate list |
| Chunk truncation | Yes | Byte-level slice |
| Judge call itself | **No** | LLM output non-reproducible even at temp=0 |
| Cost accuracy flag | Downgraded | Set to "estimated" when any judge match contributed |

Base deterministic detectors (`provable_duplicate`, `context_resend`,
`redundant_read`) are unaffected. Their results remain
bit-reproducible. LLM-judge results are a separate, opt-in layer
that adds on top.

## 11. Test plan

### 11.1 Unit tests (`tests/detect/test_llm_judge_semantic_duplicate.py`)

1. `test_disabled_by_default` — omit `enabled=True` → returns empty
   result with `enabled=False`, zero judge calls.
2. `test_enabled_but_no_api_key` — enabled=True, no env var → returns
   empty result, emits warning, does not raise.
3. `test_jaccard_pre_filter_low_similarity_skipped` — two totally
   different chunks → not sent to judge.
4. `test_jaccard_pre_filter_high_similarity_advances` — two similar
   chunks (>= 0.30 jaccard) → candidate for judge.
5. `test_byte_exact_matches_skipped` — chunks with same sha256 → not
   sent to judge (context_resend's territory).
6. `test_system_role_exempt` — chunks with role=="system" → not sent
   to judge.
7. `test_max_calls_cap` — max_calls=2 with 5 candidates → exactly 2
   judge calls made.
8. `test_hard_cap_enforced` — user sets max_calls=1000, hard cap
   500 applies.
9. `test_confidence_threshold_075_below_not_match` — mock judge
   returns confidence 0.80 → not counted as match (< 0.85).
10. `test_confidence_threshold_090_matches` — mock returns confidence
    0.90 → counted.
11. `test_parse_failure_counts_as_non_match` — mock returns invalid
    JSON → count as non-match, warn, continue.
12. `test_deterministic_candidate_selection` — same trace run twice
    → same candidate list (verdicts may differ, but pre-filter is
    stable).

All tests use a **mock judge** (no real API calls). Real-integration
test is a separate opt-in file.

### 11.2 Integration test (`tests/detect/test_llm_judge_integration.py`)

Skipped by default (`pytest.skipif` on missing `ANTHROPIC_API_KEY`).
When run manually with real key:
- One test on synthetic paraphrase pair → judge returns equivalent
- One test on obviously-different pair → judge returns not equivalent
- One test on cost tracking → judge_cost > 0.0 after N calls

### 11.3 Report integration (`tests/report/test_llm_judge_report_integration.py`)

1. `test_markdown_backward_compat_when_omitted` — no LLM judge → no
   new content.
2. `test_json_backward_compat_when_omitted` — no LLM judge → no
   `llm_judge` key.
3. `test_render_markdown_with_matches` — populated result → section
   renders with top offenders, cost, reasoning.
4. `test_render_json_with_matches` — populated result → `llm_judge`
   block with expected shape.
5. `test_cost_summary_accuracy_downgrades` — populated matches → cost
   summary `accuracy_flag == "estimated"`.

## 12. Go/No-go on corpus measurement

After implementation, integration run on a sample of 5 real CC
sessions (opt-in, my time budget on Anthropic account):

- **Metric**: `matches_found / candidate_pairs_evaluated`
- If ≥ 0.05 (5% of candidates are semantic dupes) → detector is
  useful. Enable by default in future release (still opt-in for
  cost reasons but documented as recommended).
- If < 0.01 → detector is not useful at scale. Ship as experimental,
  do not promote. Reconsider approach.
- Between → ship as-is, monitor.

**Cost budget for measurement**: ≤ $2.00 total (documented in
measurement script).

## 13. Backout plan

New package `src/clew/detect/llm_judge/` — deletion removes feature
cleanly. Existing detectors unaffected. Report renderers handle
`llm_judge=None` gracefully by design.

## 14. Commit chain (per feedback_rule_8)

1. **This prereg** — pushed, PR opened, URL returned to user. Stop.
2. On approval: implementation (`llm_judge/` package + tests +
   report integration). Single commit.
3. Real-data verification (opt-in run, uncommitted diagnostic).

No squash, no rebase.

## 15. Explicit non-commitments

- No claim about how many semantic duplicates real CC sessions will
  produce — that is what §12 measures.
- No claim about judge accuracy (equivalent-vs-not) — inherits
  documented LLM-judge failure modes (§0 sources).
- No claim about competitive differentiation on this specific axis —
  DeepEval and Confident AI offer similar LLM-judge features
  (verified in §0).
- No claim that `claude-haiku-4-5` is optimal for this task — it is
  the frozen default for v1 based on cost; users can override.
