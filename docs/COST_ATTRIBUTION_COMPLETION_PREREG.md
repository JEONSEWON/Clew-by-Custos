# Cost Attribution Completion — Pre-registration

**Status.** Pre-registration. Per `feedback_rule_8`, this document is pushed
and PR-opened before any production code change lands. Frozen positions
below are pre-committed; adjusting them after seeing implementation
results is not allowed.

## 0. Honesty preface (current state)

The Clew repo has partial cost attribution as of 2026-08-05:

- `src/clew/cost/pricing.py` supports **only one model** (Claude Sonnet 4.5)
  with 4-tier cache-aware pricing (base_input / cache_read / cache_write_5m
  / cache_write_1h / output). Verified 2026-07-19.
- `src/clew/cost/amplification.py` consumes `pricing.py` correctly with the
  4-tier structure. Ranges lower/upper by cache hit vs miss.
- **Context Resend Detector** does NOT use `pricing.py`. It takes flat
  `input_cost_table` / `output_cost_table` dicts from the caller (per
  `docs/CONTEXT_RESEND_DETECTOR_PREREG.md` §4) — single input rate per
  model, cache tiers not modeled.
- The Cascade waste-cost path uses `Span.cost_rate` (single rate).
- The report emits dollar figures per detector, but there is **no unified
  "Total analyzed / Total waste / Waste ratio" summary line** at the top.

This prereg closes those gaps so Phase 1 (per the 2026-08-05 endpoint
memo, `project_clew_future_strategy.md`) can be reported as done.

## 1. Motivation

Sonnet-only pricing blocks any trace whose LLM spans use other models
(GPT-4o, Claude Opus/Haiku, Gemini) from receiving accurate cost
figures. The current fallback silently uses `Span.cost_rate` when the
caller wired it up, and drops to $0 otherwise.

Users approaching Clew for the first time cannot answer the question
"how much did this session waste in dollars?" without ceremony. That
question is the entire framing of Tier 1 per the endpoint memo.

## 2. Pricing table expansion (frozen scope)

`src/clew/cost/pricing.py` gains a table with the following model keys.
Values are populated at implementation time from official provider
documentation and pinned via URL + verification date in a comment
adjacent to each entry.

**Frozen model list (v1):**

- `sonnet-4.5` (existing, retained)
- `sonnet-4.6`
- `opus-4.7`
- `haiku-4.5`
- `gpt-4o`
- `gpt-4o-mini`
- `gemini-1.5-pro`
- `gemini-1.5-flash`

**Per-model schema (frozen, matches existing `ModelPricing`):**

```python
ModelPricing(
    name=<provider model id string>,
    base_input_per_mtok=<float>,     # $/M input tokens (uncached)
    cache_read_per_mtok=<float>,     # $/M input tokens (cache hit); 0.0 if provider has no caching
    cache_write_5m_per_mtok=<float>, # $/M input tokens (5-min TTL cache create); 0.0 if N/A
    cache_write_1h_per_mtok=<float>, # $/M input tokens (1-hr TTL cache create); 0.0 if N/A
    output_per_mtok=<float>,         # $/M output tokens
)
```

**Provider caching support (frozen, sourced from provider docs at
implementation time):**

- Anthropic: full 4-tier
- OpenAI: has prompt caching (cache read cheaper); model as 4-tier with
  `cache_write_5m == base_input` when write is not separately priced
- Google Gemini: context caching exists; model as 4-tier where possible;
  set `cache_read_per_mtok` and leave writes at base if not documented

**Source pinning:** each entry carries a comment with the exact URL
consulted and the ISO-8601 verification date. Example format:

```python
"sonnet-4.6": ModelPricing(
    # https://docs.anthropic.com/en/docs/about-claude/pricing (verified 2026-08-05)
    ...
),
```

## 3. Model-name resolution

**Frozen lookup rule** (`get_pricing(model_name: str | None)`):

1. If `model_name` is `None` → return `DEFAULT_MODEL_KEY` pricing
   (currently `sonnet-4.5`).
2. Normalize: lowercase, strip whitespace.
3. Try exact match against the keys above.
4. Try known aliases (frozen map):
   - `claude-sonnet-4-5`, `claude-3-5-sonnet-*` → `sonnet-4.5`
   - `claude-sonnet-4-6` → `sonnet-4.6`
   - `claude-opus-4-7`, `claude-opus-4` → `opus-4.7`
   - `claude-haiku-4-5` → `haiku-4.5`
   - `gpt-4o-*` → `gpt-4o` (except `gpt-4o-mini-*` → `gpt-4o-mini`)
   - `gemini-1.5-pro-*` → `gemini-1.5-pro`
   - `gemini-1.5-flash-*` → `gemini-1.5-flash`
5. If no match → return default and emit **one-line** warning identifying
   the unknown model. Do not raise (silently defaulting to Sonnet 4.5 is
   an intentional soft-fail — user gets a cost estimate rather than a
   crash).

## 4. Context Resend Detector cost accuracy upgrade

**Current behavior (per prereg CONTEXT_RESEND §4):** uses per-call flat
`input_cost_rate`. If cache_read/cache_creation tokens exist on the LLM
span, they are lumped into `input_tokens` at ingest and multiplied by
the same rate.

**New behavior (this prereg §4):** the detector splits input token
attribution across three cost tiers when the underlying LLM span
attributes carry the tier-specific token counts:

- `llm.token_count.prompt` (uncached input) → `base_input_per_mtok`
- `llm.token_count.prompt.cache_read` (cache hit) → `cache_read_per_mtok`
- `llm.token_count.prompt.cache_write` (cache create) →
  `cache_write_5m_per_mtok` (5m is the default TTL when unspecified)

**Ingest layer additions (§3 modification):** the `llm_calls` metadata
schema per `docs/CONTEXT_RESEND_DETECTOR_PREREG.md` §3 is extended with
three additional integer fields (all optional, `None` when absent):

- `input_tokens_uncached`
- `input_tokens_cache_read`
- `input_tokens_cache_write`

**Backward compat guarantee:** existing `input_tokens` field remains and
equals the sum of the three when they are all populated (invariant
checked by test). Detectors that do not know about the split continue
reading `input_tokens` and behave exactly as before.

**Legacy fallback (unchanged):** when the LLM span carries only
`llm.token_count.prompt` without a breakdown, the detector treats the
entire input as `base_input` (worst case). `cost_accuracy_flag` remains
`"estimated"` in that case and the report emits the existing legacy
hint.

## 5. Unified cost summary in report

**Frozen additions to the report (both markdown and JSON):**

### 5.1 Report-level cost struct

New dataclass `TraceCostSummary`:

```python
@dataclass
class TraceCostSummary:
    total_llm_input_cost: float       # sum over all LLM calls, tier-aware
    total_llm_output_cost: float      # sum over all LLM calls
    total_tool_cost: float            # sum over tool spans if pricing available; else 0.0
    total_analyzed_cost: float        # = sum of the above
    total_waste_cost: float           # sum across all detectors (cascade + context_resend + future redundant_read)
    waste_ratio: float                # total_waste_cost / total_analyzed_cost when denominator > 0; else 0.0
    accuracy_flag: Literal["accurate", "estimated"]  # "accurate" iff every LLM call had tier-split tokens available
```

### 5.2 Markdown top-of-report display

Right below `# Clew Waste Report` and metadata, before existing content:

```
## Cost summary

- **Total analyzed**: $X.XX
- **Total waste (detected)**: $Y.YY  (Z.Z%)
- **Cost accuracy**: {accurate|estimated}

Breakdown by detector:
  - Provable duplicate: $A.AA
  - Context resend: $B.BB
  - (Redundant read: $C.CC — when this detector is implemented)
```

### 5.3 JSON aggregate field

Top-level `cost_summary` block matching `TraceCostSummary`. Existing
per-detector `cost_wasted` / `resent_cost` / etc keys retained
(backward compat).

## 6. Test plan

### 6.1 Pricing unit tests (`tests/cost/test_pricing.py`, new file)

1. `test_default_model_returned_when_none` — `get_pricing(None)` returns
   Sonnet 4.5.
2. `test_exact_model_match` — each frozen model key resolves to its
   own `ModelPricing`.
3. `test_alias_normalization_anthropic` — `claude-sonnet-4-5`,
   `claude-3-5-sonnet-20241022` → `sonnet-4.5`.
4. `test_alias_normalization_openai` — `gpt-4o-2024-05-13`,
   `gpt-4o-mini-2024-07-18` route correctly.
5. `test_alias_normalization_gemini` — `gemini-1.5-pro-latest` etc.
6. `test_unknown_model_defaults_with_warning` — unknown key returns
   default AND emits a `UserWarning` (not an exception).
7. `test_pricing_source_and_date_present` — every entry's module-level
   comment carries a URL and a date (source-provenance regression).

### 6.2 Cost summary tests (`tests/report/test_cost_summary.py`, new file)

1. `test_cost_summary_sums_across_detectors` — synthetic trace with
   known per-detector waste → summary aggregates correctly.
2. `test_waste_ratio_computed` — denominator > 0 case.
3. `test_waste_ratio_zero_when_no_llm` — degrade gracefully.
4. `test_accuracy_flag_accurate` — all llm_calls have tier-split
   tokens → flag is "accurate".
5. `test_accuracy_flag_estimated` — any llm_call lacks split → flag is
   "estimated".
6. `test_markdown_summary_section_present` — rendered markdown has the
   `## Cost summary` section with expected fields.
7. `test_json_cost_summary_block_present` — rendered JSON has
   `cost_summary` key with expected shape.

### 6.3 Existing test suite must remain green

All existing tests continue to pass without modification. New optional
fields are additive.

## 7. Backward compatibility

- `ModelPricing` schema unchanged.
- `get_pricing()` signature unchanged.
- `pricing.py` module: new entries only, no removals or renames.
- `llm_calls` metadata: three optional integer fields added (Nullable).
  Existing `input_tokens` retained and equals sum of split when
  populated. Consumers that read only `input_tokens` are unaffected.
- Report markdown: new `## Cost summary` section added at top. Existing
  sections retained in same positions.
- Report JSON: new top-level `cost_summary` block. Existing keys
  retained.

## 8. Out of scope for v1

- **Real-time pricing API integration.** Prices remain hand-updated with
  source + date comments. Automated refresh is a separate concern.
- **Custom user pricing overrides.** No `--pricing-override` CLI flag.
  Callers using the SDK path can still pass `input_cost_table` /
  `output_cost_table` to override at ingest, but the pricing module is
  the source of truth for CLI users.
- **Model auto-detection beyond LLM span `llm.model_name` attribute.**
  If that attribute is missing, we fall back to default with a warning
  (§3). Heuristic detection (e.g., token pattern analysis) is not in v1.
- **Non-standard cache tiers.** Only 5m/1h TTLs are modeled (matching
  Anthropic's current offering). Provider-specific longer tiers are
  ignored.
- **Redundant read detector cost line in the summary.** Placeholder in
  the markdown but not populated until that detector ships.

## 9. Backout plan

Any addition here (pricing entries, metadata fields, report sections)
is additive. If any downstream consumer breaks, revert this commit's
changes in a single follow-up commit — no data migration required.

## 10. Commit chain (per feedback_rule_8)

1. **This prereg** (`docs/COST_ATTRIBUTION_COMPLETION_PREREG.md`) —
   pushed, PR opened, URL returned to user. **Stop.**
2. On approval: implementation
   (`pricing.py` expansion + ingest layer tier-split fields +
   detector cost calc upgrade + report `cost_summary` + tests).
   Single commit.
3. Report presentation polish if needed (markdown wording iteration,
   report snippet tests). Single commit.

No squash, no rebase.

## 11. Explicit non-commitments

- Pricing values in the implementation are pinned to source + date at
  code time. They will drift; this prereg does not commit to any specific
  numeric rate.
- Provider caching semantics change (e.g., Anthropic could add new tiers).
  This prereg models the current 5m/1h shape only.
- No claim about downstream user experience or adoption — this prereg
  only fixes the internal cost attribution mechanics per Phase 1 scope.
