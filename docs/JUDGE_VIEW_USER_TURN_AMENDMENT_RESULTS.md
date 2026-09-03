# Results: the judge's view carries the request

Scores every prediction in `JUDGE_VIEW_USER_TURN_AMENDMENT_PREREG.md` §5. That
document was merged (`ad72214`) before this ran; no band was adjusted
afterwards.

Run 2026-09-03 · model `claude-haiku-4-5` · the 40 committed labels in
`docs/labels/unverified_edit_corpus_d_40.json` · raw rows in
`field_test/diagnostics/_user_turn_remeasure.RESULTS.json`.

---

## 0. Headline

**Six of six pass, and the interesting one is P3.** The request is now in
40 of 40 views, and 39 of 40 verdicts are unchanged. The change buys the
request-shaped axes their material without moving the answer to the question
that already had one.

| | prediction | result | |
|---|---|---:|---|
| P1 | precision ≥ 0.8667 | **1.0000** | PASS |
| P2 | recall stays 1.0000 | **1.0000** | PASS |
| P3 | ≥ 37 of 40 verdicts identical to the prior run | **39 / 40** | PASS |
| P4 | 0 verdicts cite evidence absent from the trace | **0** | PASS |
| P5 | parse failures ≤ 2 of 40 | **1** | PASS |
| P6 | cost per session rises < 5% | **$0.0046 → $0.0046** | PASS |

Prior run, same labels, view without the request: precision 0.9286, recall
1.0000, parse failures 1.

## 1. P1 moved, and one case is not evidence that it improved

Precision went 0.9286 → 1.0000. That is **one session flipping**, and it is
the same session that was the prior run's only false positive. At 13 labelled
positives a single flip moves precision by about 0.07, which is why §5's band
was written one false positive wide rather than at the measured value.

**The defensible claim is the negative one**: adding the request did not
degrade the answer. It is the same claim, and for the same reason, as the
six-axis probe's — *"one case out of 40 is not evidence that six questions
judge better."*

🔴 **1.0000 is a ceiling number on n=40 with 14 flagged. It is not a marketing
figure and must not be cited as an improvement.** Three different numbers near
this axis already exist and describe different things
(→ [[reference-three-precision-numbers]]); this adds a fourth, and the only
honest use of it is "unchanged within the granularity of the set".

## 2. P3 is what the document existed to test

39 of 40 identical. The request is irrelevant to *did the agent check the code
it changed*, so a judge that stayed put is a judge reading the question it was
asked. Movement would have meant the opposite — that material with no bearing
on the question was swaying the verdict — and that would have been a reason to
distrust the axes that follow, not a reason to celebrate the higher precision.

## 3. P4, and a trap in how it was checked

Two passes, both by containment against the exact view the judge received:

- **28 verdicts** cite a runner or an invocation (`pytest`, `rustc`, `./bin`,
  `*.py` …). Every claimed token is present in its own session's view.
- **33 quoted strings** across the prose evidence. All present.
- **12 verdicts** are prose-only. All but one are findings, where the evidence
  describes what is *absent* and so has no command to quote — the correct shape
  for that verdict. The remaining one is the parse failure.

★ **The first check reported 2 hallucinations that were not hallucinations.**
Both quoted a multi-line `python -c` body with real newlines, while the view
holds the tool input as JSON — newlines escaped as `\n`. The fragments were in
the view all along. A containment check between an LLM's quote and a
JSON-rendered view has to normalise escaping, or it manufactures exactly the
finding P4 makes a stop condition.

## 4. What the request being present does not settle

- **The assistant half stays lossy.** Measured on the same 40 sessions: the
  agent's own text is a **1.8% median share** of the view, 4 sessions have
  none. FM-2.6 stays blocked on data and is not pre-registered.
- **One corpus.** All 40 are single-agent coding tasks with a task statement at
  the top. A session whose request is spread across turns, or absent because it
  resumed, is not represented. 40/40 is a statement about Corpus D.
- **No new axis is enabled by this document.** FM-1.1, FM-2.3 and FM-3.1 are
  now *possible*. Each still needs its own pre-registration, its own labels and
  its own 0.70 gate. Nothing here says any of them works.

## 5. 🔴 §6 was under-specified, and this is the correction

The pre-registration said the published 0.9286 / 1.0000 would be replaced by
re-measured figures **if P3 missed**. P3 passed, so by the letter nothing
changes — and that is wrong.

The reason has nothing to do with P3. **Once the new view ships, 0.9286
describes a view the product no longer uses.** A number that accurately
describes an artifact we have replaced is a stale claim whichever way the
prediction landed.

So the shipped wording has to name the view it belongs to. Sites carrying the
figure today:

- `src/clew/report/markdown.py` — the verification block's own note
- `src/clew/__main__.py` — the CLI's summary line
- `src/clew/detect/llm_judge/verification_axis.py` — a comment, not shipped text

Recommended wording, and deliberately not "1.0000": *precision 0.9286 on the
view without the request and 1.0000 with it, on the same 40 hand-labelled
sessions.* Both numbers, so the reader sees a change that did not degrade
rather than an improvement that was not measured.

## 6. Order of what remains

1. ✅ Pre-registration merged.
2. 🔴 **`/privacy` names the request as transmitted material.** Not done. The
   code does not ship before it — §6 of the pre-registration lists a missing
   disclosure as a failure mode beside the measurement ones, and this is the
   one with a person on the other end.
3. ⏸ Renderer change and its fixture tests: written, committed, **not merged**.
4. ✅ Re-measurement (this document).
5. ⏸ The published-figure wording in §5.
6. ⏸ One new axis, in its own pre-registration.
