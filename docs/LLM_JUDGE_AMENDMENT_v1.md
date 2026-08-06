# LLM-Judge Semantic Duplicate — Amendment v1

**Status.** Amendment to `docs/LLM_JUDGE_SEMANTIC_DUPLICATE_PREREG.md`
(hereafter "base prereg"). Per `feedback_rule_8_pr_route`, this document
is pushed and PR-opened before any code change to the frozen artifacts it
touches lands.

**Motivation trigger.** 2026-08-06 Go/No-go measurement (base prereg §12)
produced ratio = 0.0252 on 5 CC sessions → SHIP-AS-IS verdict. Two
observations from that run motivate this amendment:

1. **Parser fence-stripping.** All 159 judge responses in the first
   attempt were wrapped in `` ```json ... ``` `` markdown code fences.
   Base prereg §4 says "Response MUST be valid JSON. Parse failure →
   count as non-match, log warning." A response that is valid JSON
   once the code fence is stripped is arguably "valid JSON in a
   markdown wrapper" — the base spec did not anticipate this failure
   mode.

2. **Ephemeral-ID sensitivity.** Multiple non-match verdicts cited
   `tool_use_id` differences (e.g. `toolu_abc` vs `toolu_xyz`) as the
   reason two otherwise-identical chunks were judged non-equivalent.
   These IDs are randomly generated per tool invocation and are
   orthogonal to the detection goal (paraphrased re-sends of
   user-intent content). Base prereg §1 defines equivalence as
   "different bytes but the same meaning" — the base rubric §4 does
   not explicitly address whether randomly-generated per-call
   identifiers count as "meaning".

**Honesty preface.** Both observations were discovered AFTER seeing the
2.52% Go/No-go result. This amendment could be construed as p-hacking
(adjusting the pipeline to raise the score). The counter-claim:

- The parser fence-stripping is not scope-changing; it recovers verdicts
  the judge already produced. Not clarifying it leaves the base spec
  observably under-specified.
- The ephemeral-ID clarification aligns the judge with the base
  detection definition (§1 "same meaning"). Not clarifying it treats
  random UUIDs as semantic content, which contradicts the base intent.

The reader is entitled to judge whether these changes are legitimate
clarification or post-hoc tuning. Both changes are documented explicitly
here so the record is honest. Any re-measurement after this amendment
must be reported alongside the pre-amendment 2.52% figure — not as a
replacement.

## 1. Changes to base prereg §4 (rubric)

### 1.1 System prompt — add ephemeral-ID clause

**Before (base prereg §4, verbatim):**

> "You are a strict equivalence judge for LLM message chunks. Two
> chunks are \"equivalent\" only if they express the same request,
> tool call, or information to the LLM. Formatting differences
> (whitespace, punctuation, quotation style) are equivalent. Different
> content, values, or intent are NOT equivalent."

**After (this amendment):**

> "You are a strict equivalence judge for LLM message chunks. Two
> chunks are \"equivalent\" only if they express the same request,
> tool call, or information to the LLM. Formatting differences
> (whitespace, punctuation, quotation style) are equivalent.
> **Ephemeral identifiers that are randomly generated per invocation
> (e.g. `tool_use_id`, `message_id`, `id` fields on tool calls / tool
> results) are NOT semantic content — ignore them when judging
> equivalence.** Different content, values, or intent are NOT
> equivalent."

**Diff:** one sentence added between the "Formatting differences..."
sentence and the "Different content..." sentence. No other change to
system prompt.

**User message template (base prereg §4):** unchanged.
**Confidence threshold (base prereg §4):** unchanged (0.85).
**Chunk truncation (base prereg §4):** unchanged (4000 chars).

### 1.2 Response parsing — fence-tolerance

**Before (base prereg §4, verbatim):**

> "Response MUST be valid JSON. Parse failure → count as non-match,
> log warning."

**After (this amendment):**

> "Response MUST contain valid JSON. **Common markdown code fence
> wrappers (`` ``` `` or `` ```json ... ``` ``) around the JSON body are
> stripped before parsing.** Parse failure of the (fence-stripped)
> body → count as non-match, log warning."

**Diff:** one sentence added. Behavior: `\`\`\`json\n{...}\n\`\`\``
responses are unwrapped before `json.loads`. Behavior on truly
malformed responses unchanged (still parse_failed=True).

## 2. Explicit non-changes

To make the boundary of this amendment unambiguous, the following are
NOT changed by this amendment:

- Base prereg §1 (detection definition) — unchanged.
- Base prereg §2 (opt-in gate) — unchanged.
- Base prereg §3 (judge model, determinism knobs) — unchanged.
- Base prereg §5 (candidate selection, Jaccard threshold 0.30,
  max_calls 50) — unchanged.
- Base prereg §6 (interface, dataclasses) — unchanged.
- Base prereg §7 (cost cap, hard cap) — unchanged.
- Base prereg §8 (rate limit, timeout, backoff) — unchanged.
- Base prereg §9 (deferred features) — unchanged.
- Base prereg §10 (cost attribution) — unchanged.
- Base prereg §11 (unit tests) — new tests are ADDED for the parser
  fence-stripping (see §3 below); existing tests unchanged.
- Base prereg §12 (Go/No-go thresholds) — **unchanged**. The 5% GO /
  1% NO-GO / between SHIP-AS-IS thresholds remain frozen. Only the
  measurement path (parser + rubric) is being clarified. Any
  post-amendment measurement is reported as a **separate data point**
  alongside the pre-amendment 2.52% baseline.
- Base prereg §13 (backout plan) — unchanged.
- Base prereg §15 (explicit non-commitments) — unchanged.

## 3. New tests (added to base prereg §11)

Six new unit tests in `tests/detect/test_llm_judge_anthropic_parser.py`
(added 2026-08-06):

1. `test_bare_json_parses` — baseline: no fence, valid JSON.
2. `test_markdown_fenced_json_parses` — `\`\`\`json ... \`\`\``
   wrapper stripped correctly.
3. `test_markdown_fenced_no_language_tag` — `\`\`\` ... \`\`\``
   (no `json` tag) stripped correctly.
4. `test_fence_with_trailing_whitespace` — leading/trailing whitespace
   tolerated.
5. `test_unparseable_text_still_flags_parse_failed` — non-JSON,
   non-fenced text still triggers `parse_failed=True`.
6. `test_fenced_but_body_still_invalid` — fence stripped, inner body
   still invalid → `parse_failed=True`.

A prompt-clause test is not added at unit level (the fake judge_fn
tests in `test_llm_judge_semantic_duplicate.py` don't exercise the real
prompt). The prompt clause is validated by re-measurement (§4 below).

## 4. Re-measurement plan

Same procedure as base prereg §12:

- Same 5 CC sessions (seed 42, deterministic sample from
  `data/hf_recon/trace_commons_paths.txt`).
- Same `claude-haiku-4-5` model.
- Same $2.00 total cost cap, $1.80 running-total hard-stop.
- Same Go/No-go thresholds (5% / 1% / between).

Report includes:

- Pre-amendment measurement: **ratio = 0.0252, verdict = SHIP-AS-IS**
  (baseline, retained for honesty).
- Post-amendment measurement: ratio = ?, verdict = ?.
- Delta (attribute to which change: parser vs prompt).

If post-amendment ratio ≥ 5% → GO. If < 1% → NO-GO. If between →
SHIP-AS-IS (unchanged verdict).

**Cost budget for re-measurement**: ≤ $0.30 (small run; base prereg
§12 total budget $2.00 was for the ONE measurement, and this
amendment stays under half).

## 5. Backout plan

Same as base prereg §13. This amendment adds ~1 sentence to the
system prompt and ~5 lines to `_parse_response`. Reverting either is
a single-file edit.

## 6. Commit chain (per feedback_rule_8)

1. **This amendment** — pushed as own commit on new branch, PR opened,
   URL returned to user. STOP for approval.
2. On approval: implementation (prompt clause + parser fence-stripping
   + 6 new tests). Single commit.
3. Re-measurement (opt-in run, uncommitted diagnostic; results
   documented in this file's §4 as a follow-up commit or PR update
   depending on user preference).

No squash, no rebase.

## 7. Explicit non-commitments

- No claim that this amendment will raise the ratio to GO territory.
  §4 is a re-measurement; outcome is what it is.
- No claim that the pre-amendment 2.52% is invalid. It is a legitimate
  data point under the pre-amendment spec. This amendment adds a
  second data point under a clarified spec.
- No claim that further prompt-tuning is out of scope forever. This
  amendment addresses two specific observations from the 2026-08-06
  measurement. Additional observations from future runs may warrant
  additional amendments (each with the same honesty protocol).
