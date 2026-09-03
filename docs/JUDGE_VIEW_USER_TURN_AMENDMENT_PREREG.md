# Amendment: the judge's view carries the request

Amends `VERIFICATION_JUDGE_PREREG.md` §2, *What the judge is shown* (frozen).

Rule 8: this document is merged before any code. Nothing here is implemented
yet.

---

## 0. The axis cannot see what was asked

`render_trace_for_judge` emits two things: the assistant's recovered text
blocks, and the tool calls in order with truncated outputs. **It does not emit
the user's turn at all.**

For FM-3.2 that was defensible — "did the agent check the code it changed" is
answerable from actions alone, and it scored precision **0.9286** / recall
**1.0000** on the 40 labels without ever seeing the request.

It is not defensible for the next axes. Three MAST modes take the request as
one half of the comparison, and with the request absent they are not hard
questions, they are **unaskable** ones:

| mode | the comparison it needs |
|---|---|
| FM-1.1 disobey task specification | what was asked vs what was done |
| FM-2.3 task derailment | the original objective vs where the session went |
| FM-3.1 premature termination | what was asked vs what was finished |

This document changes the frozen view so those axes become possible. **It does
not add any of them.** Each remains its own pre-registration with its own
labels and its own gate.

## 1. Measured before deciding (2026-09-03)

Two diagnostics, both over the same 40 labelled Corpus D sessions the judge
gate uses, so the numbers are comparable to each other and to the gate.

**The request is there.** `field_test/diagnostics/_user_turn_presence.py`:

| | |
|---|---|
| sessions with at least one user text block | **40 / 40** |
| sessions with none | **0** |
| user text blocks, median | 1 |
| user text characters, median | **136** |
| `tool_result`-carrying user messages separated out | 871 |

That last row is the trap this measurement had to avoid. Claude Code carries
tool results in `user`-role messages, so counting `role == "user"` would have
counted 871 tool outputs as user utterances and reported near-total coverage of
something that is not there. Text blocks and `tool_result` blocks are counted
separately; the 40/40 is text blocks only.

The median 136 characters is the task statement — the material these axes need,
and small enough that the view barely grows.

**Contrast, and why this is the change being proposed rather than a new axis.**
`field_test/diagnostics/_fm26_reasoning_presence.py`, same 40 sessions,
measured FM-2.6 (reasoning-action mismatch), which was the next axis on the
expansion plan:

| | |
|---|---|
| reasoning share of the judge's view, median | **1.8%** |
| assistant text blocks per session, median | 2 |
| sessions with zero reasoning text | 4 |
| six-axis probe flags with **zero** reasoning present | **1 of 9** |
| blocks in flagged sessions, median | **1** (vs 2 across all 40) |

FM-2.6's flags concentrate in the sessions with the least reasoning, and one
flag was raised where there was none at all. That is the shape
`unverified_edit` had before it was labelled and died at 0.3250, so FM-2.6 is
not pre-registered. The half it needs is the half our traces lose; the half
these three axes need is present in every session.

## 2. What changes

One function, `render_trace_for_judge`.

The view gains user text blocks, rendered before the actions, in first-appearance
order and deduplicated — the same treatment `_assistant_texts` already gives the
assistant side, and for the same reason: accumulated prompts repeat every earlier
turn, and a turn seen twice is one thing the user said.

```
USER ASKED: <text>
AGENT SAID: <text>
ACTION <tool>  <- changes a file
  input: ...
  output: ... (truncated at TOOL_OUTPUT_MAX_CHARS)
```

**`tool_result` blocks are excluded.** They are tool output wearing the `user`
role, they are already rendered under `ACTION`, and including them would double
the view and mislabel the machine's output as the person's words.

## 3. What explicitly does NOT change

- **The question.** §2's frozen wording is untouched.
- **The verdict shape.** `{checked, evidence, confidence}`.
- **The model.** Still read from the existing configuration.
- **`TOOL_OUTPUT_MAX_CHARS` (2,000) and `VIEW_MAX_CHARS` (120,000).** The
  request is a median 136 characters; nothing about the truncation regime
  needs to move, and moving it would change what the 0.9286 was measured on
  for a second, unrelated reason.
- **The 40 labels.** `unverified_edit_corpus_d_40.json` is not revised. This
  amendment is scored against the labels as committed.
- **No cost or waste-rate field.** `wasteful == (waste_span_count > 0)` stays
  an identity.
- **No adapter change.** The user turns come from `metadata["llm_calls"]`,
  which the adapter already produces.
- **The semantic-duplicate axis.** Untouched.
- **No new axis.** FM-1.1, FM-2.3 and FM-3.1 become possible and are not
  proposed here.

## 4. 🔴 What this sends that it did not send before

The view is transmitted to the model provider on every judged trace. Today it
carries tool inputs verbatim — file paths and commands as the trace wrote them
— plus recovered assistant text. **After this change it also carries the user's
own words.**

That is a new category, not more of the same one. A person reading a disclosure
that says "your commands and file paths are sent" would not conclude that their
prompt text is. So:

- The live `/privacy` disclosure has to name it **before this ships**, on the
  same rule that put the axis behind a disclosure in the first place.
- Nothing about this is buffered by the storage decision. `evidence` is not
  persisted, and the user's request was never going to be persisted either;
  what changes is the **transmission**, which is the part a privacy notice is
  about.
- The per-project switch (cloud `0024`) is the control that answers it. A
  project with `verification_enabled = false` sends nothing, request included.

**Order of work in §8 puts the disclosure before the code, not after.**

## 5. Predictions (written before any code)

Re-scored on the same 40 labelled Corpus D candidates, with the new view. "The
finding" is `checked: false` matching a label of `true`.

The prior run on the old view: precision **0.9286** (13 of 14 flagged were
true), recall **1.0000** (13 of 13), parse failures 1, hallucinated evidence 0.

| # | Prediction | What rejects it |
|---|---|---|
| **P1** | precision ≥ **0.8667** — at most one more false positive than the prior run | below 0.8667 |
| **P2** | recall stays **1.0000**: no true candidate is newly missed | any miss |
| **P3** | **≥ 37 of 40** verdicts identical to the prior run | 4 or more flips |
| **P4** | **0** verdicts cite evidence absent from the trace | any hallucinated quote |
| **P5** | parse failures ≤ **2 of 40** | 3 or more |
| **P6** | input cost per session rises by **< 5%** over the prior run's $0.0046 | 5% or more |

P3 is the prediction this document exists to test, and it is deliberately
two-sided in effect but one-sided in wording: the request is *irrelevant* to
"did the agent check its work", so adding it should move almost nothing. Many
flips would mean the judge is being swayed by material that does not bear on
the question, which is a reason to distrust it on the axes that follow, not a
reason to celebrate movement.

P1's bound is one false positive wide because at 13 positives a single flip
moves precision by about 0.07, and a band tighter than the measurement's own
granularity would reject noise.

**Written expectation, not a prediction:** P6 is the safest and P3 the one at
risk. The view grows by a median 136 characters against a median 31 KB session,
so cost is arithmetic. Whether a model given the task statement starts counting
"did it do what was asked" as part of "did it check" is not arithmetic.

## 6. What would make this fail

- **P3 misses (4+ flips) while P1 and P2 hold.** The change is still made,
  because the axes that need the request cannot exist without it, and the
  re-measured figures replace 0.9286/1.0000 everywhere they are published —
  README, `/product`, the report's own note. The old numbers are not kept for
  a view that no longer exists.
- **P1 or P2 misses.** The change is not made in this form. The next move is a
  separate view for the request-shaped axes, leaving FM-3.2 on the view it was
  measured on — more code and two things to keep in step, which is why it is
  the fallback and not the proposal.
- **P4 misses.** Immediate stop, same as the original §7. A judge that invents
  evidence cannot be audited.
- **The disclosure is not updated in time.** The code does not ship. This is
  not a measurement failure and it is listed here because it is the failure
  mode with a person on the other end.

Any of these is published as a result, in the same place as the `unverified_edit`
kill (0.3250), the args-only kill (0.633) and the re-read kill (0.033).

## 7. What this does not fix

- **The assistant half stays lossy.** 1.8% median share, measured above. Adding
  the request does not recover the reasoning, and FM-2.6 stays blocked on data.
- **Corpus D is one corpus.** All 40 sessions are single-agent coding tasks with
  a task statement at the top. A trace whose request is spread over many turns,
  or absent because the session resumed, is not represented here. The 40/40 is
  a statement about this corpus.
- **Multi-turn requests are not modelled.** The view will carry every user text
  block, deduplicated, in order. Whether "the request" is the first block or
  the last one is a question each following axis answers for itself.

## 8. Order of work

1. This document, merged, before any code. (rule 8)
2. **The `/privacy` disclosure names the request as transmitted material.** Web
   session's file, this session's fact. Shipped and verified live before step 3.
3. `render_trace_for_judge` emits user text blocks. Fixture tests: a turn
   appears, a `tool_result`-carrying user message does not, duplicates collapse.
4. Re-score the 40 labels on the new view. Cost at the prior run's rate is
   about **$0.18**, so this is a repeatable check rather than a one-shot.
5. Results document with all six predictions scored, including the ones that
   fail. If P3 misses, the same document replaces the published 0.9286/1.0000
   wherever they appear.
6. Only then, one new axis, in its own pre-registration.
