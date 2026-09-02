# Coverage Banner, Zero-Tool Case — Results

Measurement against the predictions in
[`COVERAGE_ZERO_TOOL_AMENDMENT_PREREG.md`](COVERAGE_ZERO_TOOL_AMENDMENT_PREREG.md)
§5, which its §9 requires be published whether it passes or not. Measured
2026-09-02, the same day the amendment merged.

**Headline: all six pass. P2 and P5 pass only after normalising one line — the
report stamps its own analysis time, so "byte-identical" is unachievable as
written, and the measurement says so rather than quietly normalising.**

| # | Prediction | Result |
|---|---|---|
| **P1** | no-tool trace: new line present, no "100.0%", no "0 of 0" | **PASS** |
| **P2** | with tools: markdown byte-identical | **PASS after normalising the stamp** · see §2 |
| **P3** | `coverage_stats` unchanged, `coverage_ratio == 1.0` on the empty case | **PASS** |
| **P4** | `excluded_reason` still `None` on the empty-tool trace | **PASS** |
| **P5** | real traces byte-identical | **PASS, 12 of 12** · same normalisation |
| **P6** | both render sites covered | **PASS** |

987 tests, 1 xfailed, ruff clean (was 979).

## 1. What the report says now (P1)

Rendered from a trace with LLM calls and no tool spans:

```
## Result

- **Waste detection (tool cascade)**: no waste detected (wasteful=False).

- **Tool mapping coverage for this trace**: no tool calls were recorded, so the
  tool-repeat detectors had nothing to examine — this is not a finding of zero
  waste. If this agent does call tools, its instrumentation may not be emitting
  tool spans.
```

Before, the second line did not exist and the report ended at the first.

## 2. ★ P2 and P5: "byte-identical" is not achievable, and that is the finding

The first run of the probe reported **12 of 12 differing** — with **identical
byte lengths**, which is what an equal-length substitution looks like. Diffing
one pair named it:

```
--- reverted
+++ amended
@@ -4 +4 @@
-- **analyzed**: 2026-09-02T03:17:47Z
+- **analyzed**: 2026-09-02T03:17:46Z
```

**One second apart. That was the whole difference, on every trace.** The report
carries its own analysis timestamp, so no two runs of it are ever literally
byte-identical — which makes P2 and P5, as worded, impossible to satisfy for
any change at all, including a no-op.

So the comparison normalises that one line and says so in the probe. With it
normalised: **12 of 12 byte-identical**, traces from 20 KB to 400 KB, rendered
on the working tree and again with the amendment's branch replaced by `False`
so the two runs differ in exactly this change.

★ This is the second prediction in two days whose wording outran what the
artifact can do (`VERIFICATION_JUDGE_SHIPPING_RESULTS` §2 rejected "byte-
identical" for a report that gains one key). **A future prereg saying
"byte-identical" about this report should say "after normalising `analyzed`".**

## 3. What did not move (P3, P4)

- `coverage_stats` on an empty-tool trace: `unique_tools_in_trace 0`,
  `recognized_tools 0`, **`coverage_ratio 1.0`**, `unrecognized_tool_names []`.
  Unchanged, deliberately (§3). The stored value stays vacuous and the
  companion count is what disambiguates it.
- `waste_rate.excluded_reason`: `None`. A trace with LLM calls and no tool
  spans was included in the aggregate before and still is.

⚠️ **A distinction found while testing P4.** `excluded_reason` reads
`metadata["llm_calls"]`, not LLM spans. A trace with neither is `no_llm_calls`
and always was; the frameworks this amendment is about **do** produce
`llm_calls` — their instrumentors emit the LLM span and skip only the tool span.
The first version of the P4 test used a trace with LLM spans and no `llm_calls`
and therefore tested the wrong case. Corrected, and the corrected fixture is
what the test carries.

## 4. Both sites (P6)

`markdown.py` renders Line A in two places: the waste-0 branch and the
waste-detected branch. The amendment's first draft noticed one. A trace can
carry waste and no tool spans at once — llm-side waste with an uninstrumented
tool layer — and that report goes down the other branch, so the test drives
exactly that shape and asserts the line is there.

Both sites now call one function, `_coverage_line_a`, which chooses the shape.
A third site would get both shapes by calling it, and a test asserts the
function returns each shape for the matching input.

## 5. The stale comment

`# Coverage line A — ALWAYS rendered, including waste-0` sat above a guard that
skipped the empty case. That mismatch is what made the amendment's first draft
assert a sentence we never shipped: two true facts, read separately, and never
run. The comment now describes two shapes and no skip, and **a test asserts the
string "ALWAYS rendered" is absent from the module** — the comment that misled
one reader cannot come back silently.

## 6. Mutations

Four, one at a time, each caught by the named test:

| Mutation | Caught by |
|---|---|
| the no-tools shape is never chosen | `test_a_trace_with_no_tool_spans_says_so` |
| the waste-detected site goes back to skipping | `test_the_no_tool_line_renders_in_the_waste_detected_branch_too` |
| the counts shape is broken for traces with tools | `test_the_with_tools_shape_is_untouched` |
| the stale comment is put back | `test_the_stale_comment_is_gone` |

## 7. What this does not fix

Haystack, Google GenAI and the Anthropic direct SDK still get **no waste
figure**, because there is still nothing to measure. A report that read
"everything is fine" now reads "we could not look". That is the difference
between a wrong answer and no answer, and nothing beyond it.

Making them measurable is upstream: the instrumentor has to emit a tool span.
`OPENINFERENCE_FRAMEWORK_EXPANSION_TIER2_RESULTS.md` identified the wrap point
that decides it — Smolagents passes because its instrumentor wraps
`Tool.__call__` directly.

## 8. Carried

**A JSON consumer that renders `coverage_ratio` without checking
`unique_tools_in_trace` will display 100% on a trace nobody could examine.**
Named in §3 of the amendment rather than fixed, because the field is stored and
pre-registered. The web layer does not render it today (checked: zero
references), and it has that guard recorded for when the dashboard does.
