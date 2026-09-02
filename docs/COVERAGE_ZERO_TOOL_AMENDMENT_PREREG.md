# Coverage Banner, Zero-Tool Case (Amendment)

Amends `COVERAGE_TRANSPARENCY_PREREG.md` §1.1 and
`COVERAGE_BANNER_AMEND_PREREG.md` §3.5. Written 2026-09-02.

★ **This document's first draft was wrong and the dry-run caught it.** §7 keeps
the correction, because the wrong version is the more obvious guess and the next
person will make it too.

---

## 0. What a report says about a trace it could not examine

Rendered just now, from a trace with LLM calls and **no tool spans**:

```
# Boxdawn Waste Report

- **trace_id**: `no-tools-single`
- **detector params**: φ=0.514345, N=2, model=paraphrase-multilingual-MiniLM-L12-v2

## Result

- **Waste detection (tool cascade)**: no waste detected (wasteful=False).
```

That is the whole report. **"No waste detected" is the only thing it says, and
the tool cascade had nothing to run on.** Zero tool spans and zero waste are
rendered as the same sentence.

`coverage_stats` knows: `unique_tools_in_trace` is `0`. The banner is
suppressed rather than adapted — `if cov["unique_tools_in_trace"] > 0`
(`src/clew/report/markdown.py:776`, and again at `:833`) — so the one place that
could say it says nothing instead.

★ **The guard is right to suppress the existing sentence.** `coverage_ratio` is
`(recognized / unique) if unique else 1.0` (`src/clew/report/_enrich.py:449`),
so without the guard Line A would read *"0 of 0 tools recognized (100.0%)"*.
The defect is not that we print a false number. It is that we print silence,
and silence reads as "clean".

## 1. Who actually sees it

Not hypothetical. `OPENINFERENCE_FRAMEWORK_EXPANSION_TIER2_RESULTS.md` names a
recurring defect class — **type A: the instrumentor emits no TOOL span** — and
three measured frameworks land in it:

| Framework | Tier verdict | Why |
|---|---|---|
| **Haystack** | FAIL, type A + C | Pipeline components are wrapped; an Agent's internal `_run_tool()` is a plain function. That report already calls this **"사일런트 실패 (예외 없음, waste 0)"** |
| **Google GenAI** | FAIL, type A | `automatic_function_calling` runs inside the SDK; only the parent LLM span is emitted |
| **Anthropic (direct SDK)** | FAIL, type A + R5 | No TOOL span, plus three separate trace ids |

Smolagents passes for one reason: its instrumentor wraps `Tool.__call__`
directly. So whether a user gets a real answer is decided upstream of us and is
invisible downstream of us.

## 2. What changes

**One rendered line, and only when `unique_tools_in_trace == 0`.** The
suppression becomes a substitution.

When `unique_tools_in_trace > 0`, every line is **byte-identical to today**.

## 3. What explicitly does NOT change

- **`coverage_stats` values.** `coverage_ratio` stays `1.0` on the empty case.
  It is stored and pre-registered, the dashboard reads it, and
  `unique_tools_in_trace == 0` already disambiguates for any machine. Moving a
  measurement to fix a sentence is the wrong direction.
  ⚠️ But a JSON consumer that renders `coverage_ratio` **without** checking
  `unique_tools_in_trace` will display *100%*. That is a real hazard for the web
  layer and it is a note to that layer, not a change here.
- **`waste_rate.excluded_reason`.** Tempting and wrong: the aggregate uses it to
  drop traces from published denominators, so a new value would silently change
  which traces are in every corpus figure. A trace with LLM calls and no tool
  spans is **not** excluded today and stays included.
- **Every detector, every threshold, every stored figure, every waste rate.**
- Lines B, C, D of the banner, and the `> 0` path of Line A.

## 4. The exact string (frozen by this document)

```python
_COVERAGE_LINE_A_NO_TOOLS = (
    "**Tool mapping coverage for this trace**: no tool calls were recorded, "
    "so the tool-repeat detectors had nothing to examine — this is not a "
    "finding of zero waste. If this agent does call tools, its "
    "instrumentation may not be emitting tool spans."
)
```

Rendered in place of `_COVERAGE_LINE_A` when `unique_tools_in_trace == 0`, at
both sites (`markdown.py:776` and `:833`). Line B already requires an idempotent
pair, so it does not render here; Line C requires `unrecognized > 0`, likewise.

## 5. Predictions

| # | Prediction | What rejects it |
|---|---|---|
| **P1** | on a trace with no tool spans the report contains the new line, and contains neither "100.0%" nor "0 of 0" | any of the three |
| **P2** | on a trace with tool spans, the markdown is **byte-identical** to the current build | any difference |
| **P3** | `coverage_stats` JSON is byte-identical in both cases, `coverage_ratio == 1.0` on the empty one | any change |
| **P4** | `waste_rate.excluded_reason` is `None` on the empty-tool trace, as today | any value |
| **P5** | the 28 Corpus A sessions produce byte-identical reports | any difference |
| **P6** | both render sites are covered — the waste-0 branch and the waste-detected branch | a trace with waste and no tool spans missing the line |

P2 and P5 say this is a wording change. P3 and P4 say it did not become a
measurement change while nobody was looking. P6 exists because there are two
call sites and the first draft of this document noticed only one.

## 6. What would make this fail

- **P2 or P5 misses**: stop. A banner fix that moves a report on a trace with
  tools is not a banner fix.
- **P3 or P4 misses**: stop and revert. Those fields are read by the storage
  layer and by the aggregate; changing them belongs to another document with its
  own predictions.
- **P1 or P6 misses**: incomplete, not unsafe. Fix and re-measure.

## 7. ★ The correction this document needed

The first draft asserted that we **ship** the sentence *"0 of 0 tools recognized
(100.0%)"*, on the strength of two facts read separately: `coverage_ratio`
returns `1.0` for an empty trace, and a comment above Line A says it is *"always
rendered (including waste-0)"*.

Both facts are true. The conclusion was false, because a guard added later —
`if cov["unique_tools_in_trace"] > 0` — makes the comment out of date. Rendering
one report showed it in ten seconds.

Two things worth keeping from that:

1. **The comment is stale and stays stale after this amendment.** "Always
   rendered" will describe a line that renders in two shapes and is skipped in
   none. Step 2 fixes the comment in the same commit.
2. This is the fourth time this project has found the difference between
   reading code and running it, and the second time in two days that the wrong
   version was the plausible one. The dry-run rule is what made the difference
   both times.

## 8. What this does not fix, said plainly

Those frameworks still get **no waste figure**, because there is still nothing
to measure. This turns a report that reads "everything is fine" into one that
reads "we could not look" — the difference between a wrong answer and no
answer, and nothing beyond that.

Making them measurable is upstream: the instrumentor has to emit a tool span.
Tier 2 identified the wrap point that decides it. That is not this document.

## 9. Order of work

1. This document, merged, before any code.
2. The render change, the stale comment, and tests. P1–P6 measured.
3. Published whether it passes or not.
