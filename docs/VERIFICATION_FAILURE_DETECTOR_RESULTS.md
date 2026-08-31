# Verification Failure Detector: Results

Measurement against the predictions in
[`VERIFICATION_FAILURE_DETECTOR_PREREG.md`](VERIFICATION_FAILURE_DETECTOR_PREREG.md)
§6, which its §8 step 6 requires be published whether it passes or not.
Measured 2026-08-31, the same day the pre-registration merged.

**Headline: `unverified_edit` is killed. Precision 0.3250 hand-labelled against
a pre-registered gate of 0.70.** The rule does not ship, and the reason is the
one §3 named as its weakness before anything was built.

| # | Prediction | Result |
|---|---|---|
| **P1** | 10 candidates on the author's sessions, matching the probe | **PASS**, 10 |
| **P2** | Corpus D yields at least 40 candidates | **PASS**, 522 |
| **P3** | precision ≥ 0.70 on 40 random labelled candidates | **MISS**, **0.3250** |
| **P4** | Corpus D candidate rate within 5 to 40% | **MISS**, 80.8% |
| **P5** | every cost and waste-rate figure bit-identical | **PASS** |

Both of the two the pre-registration expected to be at risk missed, and it said
which order they would miss in: *"P4 is the one most likely to miss"* and
*"P3 is the one that matters"*.

## 1. Why it died: a check is not a test runner

The frozen verification list in §3 was eighteen commands, all of them test,
build or lint runners. On 1,017 Claude Code sessions we did not generate, that
is not how code gets checked.

Of the **522 candidates**, measured over the whole population rather than the
sample:

| | |
|---|---|
| ran the edited file directly (`python solution.py`, `node buffer.js`) | **336** (64.4%) |
| used `python -c` to exercise what they had written | **75** (14.4%) |
| ran no shell command at all | 112 (21.5%) |
| **ran some check route the frozen list does not know** | **384 (73.6%)** |

And 73.6% understates it. Labelling the sample turned up two more routes the
population probe also missed: `rustc --test find_duplicates.rs && ./find_duplicates_test`,
and `node find_duplicates.test.js` — a test file executed by name rather than
through a runner.

Under §5.2's labelling rule, which counts a candidate false if it verified by
**any** route including ones the list misses, those are all false positives.

**Precision: 13 of 40.** Clopper-Pearson 95% two-sided
**[0.1857, 0.4913]**; the interval does not reach the gate either.

The 13 true positives share one shape. Eleven ran **no shell command at all**;
the other two ran only `ls`. Nothing in that population edited code, ran
something, and had it missed by the list. **The signal that survives is "no
execution", and it is not the signal the rule was written around.**

## 2. What it would take, and why it is not done here

"A session that edited checkable code and executed nothing at all" is a
narrower rule with visibly better precision on this data. It is not adopted
here, because adopting it now would be choosing the rule after seeing which one
the numbers favour, and §7 says in as many words that widening the list after
seeing the number is not available. **It needs its own pre-registration**, with
its own predictions written before it is run.

Two things that new document would have to face, both visible above:

- **"Executed nothing" is much rarer**: 112 of 522 candidates here, 21.5%. A
  precision claim on it needs a sample from that 112, not from the 522.
- **It is a different claim.** "Nobody ran a test" and "nobody ran anything"
  are not the same finding, and the second is closer to "the session ended
  early" (FM-3.1, out of scope) than to "verification was incomplete".

## 3. P4 missed, and it says the 20.0% was a habit

The rule flagged 20.0% of checkable-editing sessions on the author's machine
and **80.8%** on Corpus D, against a predicted 5 to 40%.

Per category, on the sessions that edited checkable files:

| category | flagged | |
|---|---|---|
| `data_processing` | 54/54 | 100% |
| `debugging` | 54/54 | 100% |
| `math_problems` | 76/76 | 100% |
| `refactoring` | 55/55 | 100% |
| `supplement` | 53/66 | 80.3% |
| `algorithms` | 96/128 | 75.0% |
| `api_integration` | 5/7 | 71.4% |
| `code_generation` | 126/203 | 62.1% |

Four categories at 100% is its own finding: a rule that flags every session in
a category is not discriminating inside it. And 344 of the 522 candidates have
exactly **one** checkable edit, which is the shape of a short benchmark task
rather than of a codebase being worked on.

**This is a limit on the claim, not a limit on the corpus.** Corpus D was
adopted precisely because it is not ours; what it says here is that "how often
does an agent skip its tests" has no single answer across authors and task
shapes, and a detector reporting it needs to say whose sessions it was
calibrated on.

## 4. P5 passes by construction, and that is worth saying

No module under `src/` imports the rule. The §29.2 tool-error gate is
untouched, no cost field, `waste_span_count`, `waste_cost` or waste rate reads
anything this produced, and `wasteful == (waste_span_count > 0)` is still an
identity. Checked by looking for importers rather than by re-running the
85-session scan, because a rule nothing imports cannot move a number and the
scan would have been theatre.

**If a future pre-registration wires a rule of this family into the report, P5
has to be re-checked there.** It is cheap to satisfy today only because nothing
consumes it.

## 5. What P1 was for, and what it caught

P1 asked the implementation to reproduce the probe's 10 exactly. It did, on the
same ten sessions with the same per-session counts.

That is a small result with a specific job: the probe reads session `jsonl`
directly and the rule reads spans built by the adapter, and the two can
disagree. A tool call with no matching result never becomes a span; a path key
the adapter serialises differently would silently drop edits. Had P1 come in at
9 or 11, §7 says to stop before labelling anything, and 40 labels would have
been spent measuring a rule nobody had implemented.

## 6. Two things found on the way that outlive the rule

**The signal is already read and discarded.** The §29.2 tool-error gate
excludes `is_error` spans from cost as infrastructure noise
(`src/clew/ingest/claude_code.py:469`). That is right for cost and exactly
wrong for failure detection. This rule never needed it; the companion rule that
did, FM-3.3, is blocked for want of data: of 384 error results across the
author's sessions, **six** came from a verification command.

**The taxonomy percentages this plan was quoting are not in the paper.** The v1
HTML of arXiv 2503.13657 gives category-level structure and states only that
"percentages represent how frequently each failure mode and category appeared in
our analysis of 151 traces". The per-mode numbers — 8.2% for FM-3.2, 9.1% for
FM-3.3, 15.7% for FM-1.3 — exist inside Figure 2 as an image. They may be read
correctly from it, but they are not text-citable, and the coverage arithmetic
built on them needs the figure named as its source. Nothing in this document or
its pre-registration rests on them.

## 7. Where coverage stands

Unchanged. One of fourteen failure modes is reached deterministically, and it is
the one that was already reached. FM-3.2 was attempted and its rule did not
survive its own gate; FM-3.3 is blocked for want of data.

The two kills in this area now read the same way. The re-read detector reached
0.000 to 0.033 (`REREAD_DETECTOR_PREREG.md` §11); args-only real-time blocking
reached 0.633 against the same 0.70 (`reference_args_only_kill`); this reached
0.3250. In all three the structure was visible in the trace and the
**interpretation** was not, and in all three that was found by hand-labelling
rather than by argument.

The rule is kept as `field_test/diagnostics/unverified_edit_rule.py`, where the
numbers that killed it can be reproduced, rather than under `src/`.
