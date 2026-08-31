# Verification Judge (Pre-registration)

**Status.** Second attempt at FM-3.2, by a different method. The first attempt
is killed and published
([`VERIFICATION_FAILURE_DETECTOR_RESULTS.md`](VERIFICATION_FAILURE_DETECTOR_RESULTS.md));
this document does not reopen it. Per `feedback_rule_8` it is pushed and
PR-opened **before any code lands**. The design in §3, the predictions in §6 and
the rejection conditions in §7 are frozen positions. Adjusting them after seeing
results is not allowed.

---

## 0. Why, and what number this has to beat

`unverified_edit` reached **precision 0.3250** hand-labelled against a
pre-registered 0.70 and was killed. The cause was specific and measured: the
frozen list of eighteen verification commands encoded *"a check is a test
runner"*, and on 1,017 sessions from elsewhere a check is mostly *"run the thing
you just wrote"* — 336 of 522 candidates ran the edited file directly.

That is not a tuning failure. Every route a structural rule could enumerate is
one more item on a list that the next corpus will not match. The question
"did this session check its work?" is an interpretation, and three kills in this
codebase now say the same thing about interpretation: `REREAD_DETECTOR_PREREG`
§11 at 0.000 to 0.033, `reference_args_only_kill` at 0.633, and this one at
0.3250. In all three the structure was in the trace and the meaning was not.

So the judge takes the same question, on **the same 40 candidates, against the
same labels**, and has to clear the same gate.

## 1. The shape: candidates from structure, verdict from the judge

Not a judge that reads every session. The killed rule becomes a **candidate
generator** and the judge becomes the **confirmation stage**, which is how the
existing cascade already works: cheap structural matching proposes, expensive
semantic confirmation decides.

```
unverified_edit (structural)  ->  522 candidates from 1,017 sessions
                                  precision 0.3250 on the labelled 40
        + judge confirmation  ->  fewer candidates, and §6 P1 says how precise
```

This matters for cost and for honesty. The structural stage already discards
495 of 1,017 sessions for free; the judge is asked only about the 522 the
structure could not settle. And because the labelled 40 are drawn from those
522, the comparison is **the same data, the same labels, two methods**. There is
no corpus change to explain a difference away.

★ The killed rule keeps its home in
`field_test/diagnostics/unverified_edit_rule.py`. It is not restored to `src/`
by this document. If the judge passes, what ships is the pair, and that is a
separate decision recorded in the results.

## 2. What the judge is asked

One question, frozen here:

> Given this agent session, did the agent check the code it changed, by any
> means? Running a test runner, executing the edited file, importing it and
> exercising it, compiling it, or reading back a result all count as checking.
> Editing a file and never running anything that would reveal a mistake does
> not.

Answer shape, frozen: `{"checked": true|false, "evidence": "<the command or
action that decided it, verbatim if present>", "confidence": 0.0-1.0}`.

`checked: false` is the finding. `evidence` is required in both directions and
exists so a wrong verdict can be read afterwards; a verdict whose evidence
quotes something not in the trace is a hallucination and §6 P4 counts them.

**What the judge is shown**, frozen: the session's tool calls in order, each as
`tool name + input`, plus the assistant text blocks, with tool outputs
truncated to 2,000 characters each. Not the raw file. The reason is not cost:
tool outputs are where the bulk of a trace is and they are not evidence about
whether a check was run, while a truncated output still shows that it ran.

**Model**, frozen: the same model the existing judge axis uses, read from the
existing configuration rather than chosen here, so the two axes cannot drift
apart silently.

## 3. What it costs

Stated before measuring.

The 40 labelled candidates total **1.70 MB**, about **0.42 M input tokens**
(mean 42 KB, median 31 KB, max 357 KB per session). One scoring pass over the
whole labelled set is a single-digit number of dollars at current input prices,
and the pass is repeatable.

Running the judge over all 522 candidates would be roughly 13 times that. **That
is not done in this document.** §8 scores the 40 first, and a full-population
pass happens only if the gate is met.

The existing client is reused: retries with backoff, per-call timeout, cost
accounting and parse-failure handling all already exist in
`AnthropicJudge`. What is new is a prompt and a verdict shape; the current axis
is hard-wired to a two-chunk equivalence question and cannot answer this one.

## 4. What is explicitly NOT changed

- **No adapter change.** The judge reads what the Claude Code adapter already
  produces. Assistant text is recovered from the accumulated prompts in
  `metadata["llm_calls"]`, which is lossy (measured: about one text block per
  twenty tool calls survives there), and that loss is a limit on this document's
  claim rather than a reason to touch ingest. Every published measurement sits
  on that layer.
- **No cost or waste-rate field.** Nothing this produces enters
  `waste_span_count`, `waste_cost`, either waste rate, or any stored `run`
  column. `wasteful == (waste_span_count > 0)` stays an identity.
- **The §29.2 tool-error gate stays.** This axis does not read `is_error`.
- **The existing judge axis is untouched.** `semantic_duplicate` keeps its
  prompt, its threshold and its results.
- **No alert.** Whether a verification failure should ever page anyone is a
  separate question with its own pre-registration. This document produces a
  number, not a notification.
- **The killed structural rule stays killed** as a standalone finding. It is
  used here only as a candidate generator.

## 5. The rejection this must survive

**0.70 precision on our own hand labels.** Same gate, same 40 labels, already
committed in `docs/labels/unverified_edit_corpus_d_40.json` before any judge
existed. The labels cannot be revised in light of judge output; if a label is
found to be wrong, the correction is published as a correction and the run is
re-scored with both figures shown.

Two specific hazards this design has to avoid, both named before building:

**A judge scored against another judge is not validated.** The MAST authors
released 1,642 annotated traces
([`mcemri/MAST-Data`](https://huggingface.co/datasets/mcemri/MAST-Data),
CC-BY-4.0), and their README says in as many words: *"Annotations are produced
by an LLM judge, not by human labelling."* Their human-labelled file is 19 rows
and its own README says the taxonomy revisions differ per round and *"the codes
are not comparable across rounds"*. **Those labels are not used as ground truth
anywhere in this document.** They appear in §8 only as a sampling aid for a
later, separate corpus check.

**A judge that agrees by always saying the same thing is not a judge.** The
labelled set is 13 true and 27 false. A judge answering `checked: true` for
everything scores 27/40 on accuracy while finding nothing, so §6 gates on
precision **and** recall of the finding, not on accuracy.

## 6. Predictions (written before any code)

Scored on the 40 labelled Corpus D candidates. "The finding" is
`checked: false`, matching a label of `true` (the session really did not check).

| # | Prediction | What rejects it |
|---|---|---|
| **P1** | precision of the finding ≥ **0.70** | below 0.70 |
| **P2** | recall of the finding ≥ **0.60**: at most 5 of the 13 true candidates are missed | below 0.60 |
| **P3** | the judge beats the structural rule's **0.3250** on this identical set | at or below 0.3250, which would say the interpretation layer added nothing |
| **P4** | **0** verdicts cite evidence absent from the trace | any hallucinated evidence quote |
| **P5** | parse failures ≤ **2 of 40** | 3 or more |

P1 and P2 together are the gate. P3 is the comparison the whole document exists
for and is deliberately separate from P1: a judge could clear 0.70 and still be
worse than a cheaper rule on some other set, and here it cannot hide behind a
corpus change.

**Written expectation, not a prediction:** P2 is the one at risk. The 13 true
candidates are sessions that ran nothing at all, which is the easy half; the
hard half is the 27 that verified by an unusual route, and those affect P1.

## 7. What would make this fail

- **P1 misses**: the judge does not clear the bar the structural rule failed,
  and FM-3.2 is reported as not reachable by either method on this evidence.
  The next move is a different corpus, not a different prompt: re-prompting
  after seeing the number is the thing pre-registration exists to prevent.
- **P2 misses while P1 passes**: shipped as a precision-first filter with the
  measured recall stated as a limit, because a missed failure is cheaper than a
  false alarm for a signal nobody has learned to trust yet.
- **P3 misses**: published as a negative result about the judge, not about the
  question. It would mean the structural rule's errors and the judge's errors
  fall in the same places.
- **P4 misses**: immediate stop. A judge that invents evidence cannot be
  audited, and the evidence field is the only thing making its verdicts
  checkable.

Any of these is published as a result, in the same place as the missed Corpus D
prediction, the rejected latency P5, and the `unverified_edit` kill.

## 8. Order of work

1. This document, merged, before any code. (rule 8)
2. The prompt and verdict shape added beside the existing axis, reusing the
   client. A fixture test that the verdict parses, and one that a
   `checked: true`-for-everything judge fails P2, so the guard in §5 is
   exercised rather than asserted.
3. Score the 40. Compute P1 through P5. Stop here if P1 misses.
4. Publish the result whether it passes or not, including the per-candidate
   verdicts next to the committed labels so a reader can check both.
5. Only if the gate is met: a second, independent check on
   `mcemri/MAST-Data`'s FM-3.2 subset. Their labels stratify the sample (20 they
   marked 1, 20 they marked 0) and **we hand-label those 40 ourselves** before
   scoring. Disagreement with their judge is reported as its own finding rather
   than as an error on either side.
6. Only after that: whether this ships, and whether it feeds an alert, each as
   its own decision.

Step 5 is not a validation of step 3. It is a second corpus, in a different
family of agent frameworks, read as text because MAD's trajectories are raw
per-framework logs with no structured spans and, for 48% of them, no per-step
timestamps at all.
