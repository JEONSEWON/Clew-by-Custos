# Context Resend Detector — Pre-registration

**Status.** Pre-registration. Per `feedback_rule_8`, this document is pushed
and PR-opened before any production code change lands. Thresholds and
Go/No-go conditions below are the pre-committed frozen positions; adjusting
them after seeing implementation results is not allowed.

## 0. Honesty preface (what this measurement is and is not)

The frequently-cited number "**62% of an agent inference bill is re-sent
context**" is not sourced cleanly. Tracing the citation chain:

- InfoQ (May 2026): GitHub reports **62% Effective Token reduction** on 12
  internal workflows via a *combination* of MCP tool pruning, gh CLI
  substitution, and daily audit agents. This is total optimization achieved,
  not the resend share of the bill.
- Stanford Digital Economy Lab: "The high cost is in input tokens rather than
  output." Qualitative claim, no specific percentage.
- The "30 engineering teams audited" attribution used in earlier planning
  notes could not be verified against a primary source.

**Consequence for this prereg.** We do not claim that a Context Resend
Detector "covers 62%" of anything. The detector's purpose is precisely to
produce our own primary-source measurement on Clew-accessible corpora.
Marketing language derived from unverified attributions is out of scope.

## 1. Detection definition (deterministic signals only)

Given a trace containing one or more LLM calls, a **context resend event** is
emitted when both hold:

1. **Chunk-level exact match.** A message chunk `c` (see §2 for chunk
   boundary) appears in the input of `n ≥ 2` LLM calls within the same
   trace, where equality is `sha256(c) == sha256(c')` — byte-exact.
2. **Not a system-role chunk.** Chunks whose parsed structure identifies the
   role as `"system"` (case-sensitive) are exempt. Rationale: system prompt
   reuse across turns is standard practice, not waste.

When both hold, all occurrences after the first are flagged as **resent**.
The first occurrence is not flagged (necessary payload).

## 2. Chunk boundary rule

For each LLM span, `input_text` is parsed as JSON. Chunk assignment follows
this priority (first match wins, deterministic):

1. **JSON list** → each list element is one chunk. Element is re-serialized
   with `json.dumps(elem, sort_keys=True, ensure_ascii=False)` before
   hashing.
2. **JSON dict with `messages` key** whose value is a list → each element
   of `messages` is one chunk. Same re-serialization rule.
3. **Any other JSON parse success or parse failure** → the entire
   `input_text` string is one chunk. This preserves detection of full-prompt
   resend even when structure is unrecognized.

**Role extraction (for §1.2 system exemption):** if the chunk is a dict
with a `"role"` key, that value is the role. If not, role is unknown and
the chunk is included in resend counting (no exemption).

**Chunk boundary is data-driven, not tokenizer-driven.** Boundaries are set
by the trace's own message array structure, so tokenizer version cannot
affect what constitutes a chunk.

## 3. Preserving LLM inputs across preprocess

Current `preprocess_trace` (`src/clew/ingest/preprocess.py`) removes all LLM
spans in step 3 (`collapse_llm_spans`). Their `input_text` and per-side
token/cost data disappear from the post-processed `Trace`, blocking any
downstream detector that needs input-side accounting.

**Modification (§3 of this prereg is the only change to preprocess):** the
`collapse_llm_spans` function records LLM input data in the returned trace
metadata under the new key `llm_calls`, a list ordered by span start_time:

```
trace.metadata["llm_calls"] = [
    {
        "span_id": <str>,
        "input_text": <str>,                  # original attrs["input.value"] verbatim
        "input_tokens": <int|None>,           # from attrs["llm.token_count.prompt"]
        "output_tokens": <int|None>,          # from attrs["llm.token_count.completion"]
        "input_cost_rate": <float|None>,      # from input_cost_table[model], §4
        "output_cost_rate": <float|None>,     # from output_cost_table[model], §4
        "cost_rate_legacy": <float|None>,     # existing single cost_rate on span, fallback path §4
        "model": <str|None>,
        "start_time": <ISO 8601 UTC str>,
    },
    ...
]
```

**Reading input/output tokens.** The OpenInference standard exposes
`llm.token_count.prompt` and `llm.token_count.completion` as separate
attributes on LLM spans. The existing ingest code reads only
`llm.token_count.total`. The modification reads the two side-specific
attributes at collapse time (before the LLM span is removed) and stores
them in the metadata entry. Both values are `None` if the attribute is
absent — the detector treats `None` as "cannot compute per-side cost;
degrade to legacy path" (§4).

**Backward compatibility.** Existing consumers of `trace.metadata` do not
read `llm_calls`, so the addition is non-breaking. The `collapsed_llm_spans`
count key is preserved. Existing detectors (`structural.py`, `cascade.py`)
are not modified.

**Frame-preservation invariant.** The `input_text` recorded here is the
verbatim value present on the LLM span before any transformation. No
`extract_output_text` mutation is applied (that stage operates on
`output_text`, not `input_text`).

## 4. Cost estimation (accurate path + legacy fallback)

The waste attributable to a resent chunk is estimated per-call by
apportioning the LLM span's total input-side tokens to the resent chunks
proportionally to per-chunk tokenized length:

```
share(c) = tiktoken_len(c) / sum(tiktoken_len(c_i) for c_i in call.chunks)
resent_input_tokens(c) = round(share(c) × call.input_tokens)
resent_cost(c) = resent_input_tokens(c) × input_cost_rate
```

**Rationale for apportionment.** Provider-reported `llm.token_count.prompt`
is the authoritative input token count for a call, matching what the
provider actually bills. `tiktoken` is used only to compute *relative*
share of chunks within a call, not the absolute token count. This isolates
`tiktoken` version drift from the per-chunk numbers (only ratios matter,
absolute counts come from the provider).

**Accurate path (preferred).** When the caller passes
`input_cost_table` (and optionally `output_cost_table`) to the ingest
function:

```python
ingest_from_openinference_json(
    path,
    *,
    input_cost_table: dict[str, float] | None = None,   # $/input-token per model
    output_cost_table: dict[str, float] | None = None,  # $/output-token per model
    cost_table: dict[str, float] | None = None,         # legacy single rate, preserved
) -> Trace
```

then `input_cost_rate` and `output_cost_rate` in the `llm_calls`
metadata entry are populated from these tables. The detector uses
`input_cost_rate` directly for accurate monetization.

**Legacy fallback path (backward compatible).** When only the existing
`cost_table` is provided (no `input_cost_table`), `input_cost_rate` in
metadata is `None` and `cost_rate_legacy` carries the existing single-rate
value. The detector then computes cost as
`resent_input_tokens × cost_rate_legacy`. This matches current provable
duplicate detector behavior (single-rate) and is honestly imprecise —
input tokens are typically 20-25% of the blended rate on Claude/OpenAI
models. The detector marks the result with `cost_accuracy_flag =
"estimated"` and the report emits a one-line notice suggesting
`input_cost_table` configuration for accurate figures.

**Tokenizer (for share calculation only).** `tiktoken` is used with the
encoding matched to the model (cl100k_base for GPT-4 family, o200k_base for
GPT-4o, cl100k_base for Anthropic Claude family as an approximation).
Unknown models fall back to `char / 4` as a rough proxy. **Because these
values enter only into `share(c)` (a ratio), tokenizer imprecision does
not distort absolute token counts — only the split among chunks within a
call.**

**Determinism of tiktoken.** tiktoken is pinned by version in
`pyproject.toml`. Same input + same version → same token count. Version
bump is a controlled change, not a runtime source of variance.

**Determinism of accurate path.** All inputs (provider token counts, user
cost tables, chunk hashes, chunk shares) are deterministic on a given
trace. Same trace + same tables → byte-identical result.

## 5. Detector interface

New file: `src/clew/detect/context_resend.py`.

```python
CostAccuracy = Literal["accurate", "estimated"]

@dataclass
class ContextResendResult:
    trace_id: str
    resent_events: list["ResentEvent"]          # one per resent chunk occurrence
    resent_input_tokens: int                    # sum over resent_events
    resent_cost: float                          # sum over resent_events
    total_llm_input_tokens: int                 # denominator for the ratio
    total_llm_input_cost: float                 # denominator (input side)
    cost_accuracy_flag: CostAccuracy            # "accurate" if input_cost_table used;
                                                # "estimated" if legacy fallback (§4)

@dataclass
class ResentEvent:
    llm_span_id: str          # the LLM call carrying the resent chunk
    origin_llm_span_id: str   # the LLM call that first sent this chunk
    chunk_hash: str           # sha256 hex
    chunk_role: str | None    # if extractable
    resent_input_tokens: int
    resent_cost: float


def find_context_resend(trace: Trace, n: int = 2) -> ContextResendResult: ...
```

**No label imports.** This detector does not read the eval or dev set
directory (matches the leakage-guard convention of `detect/__init__.py`).

## 6. Test plan

### 6.1 Unit tests (`tests/detect/test_context_resend.py`, new file)

Fixtures use hand-constructed `Trace` objects with LLM inputs populated in
metadata (per §3 modification).

1. `test_identical_prompt_across_two_calls` — two LLM calls with identical
   input list → all chunks after first are resent.
2. `test_partially_overlapping_messages` — call 2 has messages
   `[a, b, c]`, call 1 had `[a, b]` → `a` and `b` are resent, `c` is not.
3. `test_system_role_exempt` — system-role chunk appearing in every call →
   zero resent events.
4. `test_unparseable_input_falls_back` — non-JSON `input_text` in both
   calls with identical content → one full-prompt resent event (fallback
   chunk path).
5. `test_role_missing_no_exemption` — dict chunk without `role` key
   repeats → counted as resent.
6. `test_no_llm_calls_returns_empty` — trace with only tool spans → empty
   result, no error.
7. `test_single_llm_call_returns_empty` — one LLM call, no repeats
   possible → empty result.
8. `test_accurate_cost_path` — llm_calls metadata has `input_cost_rate`
   populated → result has `cost_accuracy_flag == "accurate"` and cost
   uses input rate.
9. `test_legacy_fallback_cost_path` — llm_calls metadata has
   `input_cost_rate == None` and `cost_rate_legacy` populated → result
   has `cost_accuracy_flag == "estimated"` and cost uses legacy rate.
10. `test_share_apportionment` — call with `input_tokens=100` and three
    equal-length chunks → each chunk gets `resent_input_tokens = 33` or
    34 (deterministic rounding).

Deterministic assertion: running the detector twice on the same trace
produces byte-identical `ContextResendResult` (verified via `repr()`
comparison).

### 6.2 Ingest tests (`tests/ingest/test_preprocess_llm_calls_preserved.py`,
new file)

1. `test_llm_calls_populated_after_preprocess` — trace with LLM spans →
   `trace.metadata["llm_calls"]` contains one entry per original LLM span,
   ordered by start_time.
2. `test_llm_calls_verbatim` — recorded `input_text` matches original span
   `input_text` exactly (no `extract_output_text` mutation).
3. `test_llm_calls_absent_when_no_llm` — trace with only tool spans →
   `llm_calls` is either absent or empty list; existing behavior unchanged.
4. `test_llm_calls_input_output_tokens_populated` — LLM span with
   `llm.token_count.prompt=100` and `llm.token_count.completion=50` →
   metadata entry has `input_tokens=100`, `output_tokens=50`.
5. `test_llm_calls_input_cost_table_populated` — ingest called with
   `input_cost_table={"claude-sonnet-4.5": 3e-6}` on a span with that
   model → metadata entry has `input_cost_rate=3e-6`.
6. `test_llm_calls_legacy_cost_table_fallback` — ingest called with only
   `cost_table={"claude-sonnet-4.5": 9e-6}` → metadata entry has
   `input_cost_rate=None` and `cost_rate_legacy=9e-6`.

### 6.3 Existing test suite must remain green.

All existing tests in `tests/` continue to pass without modification. No
existing behavior is altered by this change; only metadata is added and
optional ingest parameters are introduced with `None` defaults.

## 7. Go/No-go on corpus measurement

After implementation, the detector is run on Clew-accessible trace corpora.
Product targets both coding agents (Claude Code, Cursor, Aider, Cline) and
multi-agent frameworks (LangChain, CrewAI, AutoGen); Go/No-go is judged on
the aggregate across both target classes.

Denominator is `total_llm_input_cost` (§4). Numerator is `resent_cost`. The
pre-committed decision rule (frozen, aggressive):

- **`resent_cost / total_llm_input_cost ≥ 0.20`** on the aggregate corpus
  → **GO.** Context Resend Detector becomes a hero feature of the waste
  audit reframe. Ship in the next minor release.
- **`< 0.10`** → **NO-GO for hero status.** Detector remains available as
  an opt-in secondary check. Priority shifts to a redundant-read detector
  covering coding agent workloads (76.1% read consumption per SWE-Pruner
  arxiv:2601.16746, subject to its own prereg).
- **`0.10 ≤ ratio < 0.20`** → **MIXED.** Detector ships but is not
  positioned as the hero. Redundant-read detector prereg proceeds in
  parallel.

**Corpus definition (frozen for this measurement):**

1. **Coding-agent corpus (Claude Code)** — random sample of `≥ 100` traces
   from the trace-commons corpus already used by other Clew evaluations.
   Random = `random.Random(seed=42).sample(all_traces, 100)`, with the
   seed fixed in the measurement script for reproducibility.
2. **Multi-agent framework corpus (OpenInference)** — every trace available
   under `field_test/diagnostics/framework_expansion_dumps/` that contains
   at least one LLM span. Not sampled; all included.

**Reporting layout (frozen):**

The measurement script emits three ratios:

- `ratio_coding` = resent_cost / total_llm_input_cost on Corpus 1 alone
- `ratio_framework` = resent_cost / total_llm_input_cost on Corpus 2 alone
- `ratio_aggregate` = (sum resent_cost across both) / (sum
  total_llm_input_cost across both)

**The Go/No-go decision uses `ratio_aggregate` only.** The per-corpus
ratios are reported for interpretation and for detecting large
divergences: if `|ratio_coding - ratio_framework| > 0.15`, the divergence
is flagged in the measurement report and the interpretation section calls
out that the aggregate hides target-class heterogeneity.

**Confidence reporting.** The point estimate is a ratio, not a proportion,
so binomial CIs do not apply directly. Report for each of the three
ratios:

- point estimate
- 95% bootstrap interval (`n_boot=1000`, seed=42) over per-trace ratios,
  weighted by per-trace `total_llm_input_cost`

Corpus manifest sha256 is emitted with the measurement (per
`feedback_manifest_hashes_artifacts`).

**Cost accuracy in the measurement.** For the Go/No-go run, both
`input_cost_table` and `output_cost_table` are supplied from public
provider pricing as of the measurement date. The measurement report
records the pricing snapshot used. This means the Go/No-go itself runs on
the accurate cost path (§4), not the legacy fallback.

## 8. Determinism guarantee (summary)

| Component            | Deterministic? | Source of guarantee                    |
|----------------------|----------------|----------------------------------------|
| sha256 chunk hash    | Yes            | Cryptographic                          |
| Chunk boundary       | Yes            | JSON parse of trace data               |
| System-role check    | Yes            | Byte-exact string compare              |
| tiktoken length      | Yes            | Version-pinned                         |
| Cost multiplication  | Yes            | Float × float (bit-exact on same CPU)  |
| Bootstrap CI in §7   | Yes            | Fixed seed                             |

**No LLM-as-judge in v1. No embedding in v1.** These are consciously
deferred (see §9).

## 9. Explicitly out of scope for v1

- **Paraphrase resend.** Requires embedding or LLM comparison. Introduces
  non-determinism (model version, floating-point drift). Deferred until
  §7 GO decision confirms hero status.
- **Partial-chunk resend.** A chunk that is 80% identical but with one
  edited sentence will not match by sha256. Diff-based detection would
  require choosing an edit distance threshold; deferred.
- **Cross-trace resend.** If a session spans multiple trace files, resend
  across files is not detected. In-trace only.
- **Auto-caching / prevention.** This is Phase 2 territory (auto-idempotency
  layer). This prereg is Phase 1: detection only.
- **Output-token resend cost.** Only input-token cost is estimated. Output
  tokens are new content by definition and are excluded from waste.
- **Cost model refactor beyond LLM spans.** This prereg introduces split
  input/output cost tables at the ingest layer and stores split fields in
  the new `llm_calls` metadata only. Existing detectors (`cascade.py`,
  `structural.py`) continue to consume the single-rate `Span.cost_rate`
  and are not modified. A comprehensive refactor of `Span.cost_rate`
  itself is a separate future prereg.

## 10. Backout plan

If test suite fails or `trace.metadata` addition breaks any downstream
consumer, the change is reverted in one commit. No data migration is
required — the metadata addition is purely additive and no persisted
artifact reads this key.

## 11. Commit chain (per feedback_rule_8)

1. **This prereg** (`docs/CONTEXT_RESEND_DETECTOR_PREREG.md`) — pushed,
   PR opened, URL returned to user. **Stop.**
2. On approval: implementation (`preprocess.py` modification +
   `context_resend.py` + tests). Single commit.
3. Report integration (`report/_enrich.py` or equivalent + report model
   fields). Single commit.

No squash, no rebase. Three commits chain preserved.

## 12. Explicit non-commitments

- No claim that context resend covers a fixed proportion of the market
  waste bill. See §0.
- No claim about market adoption of "waste audit" framing. That is a
  separate marketing question and is not gated by this prereg.
- No claim that this detector will meet §7 GO. The measurement is the
  question, not the answer.
