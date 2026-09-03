# FM-1.1 on real sessions: did the agent do what the turn asked?

Rule 8: merged before any code. Nothing here is implemented.

FM-1.1, verbatim from arXiv 2503.13657 v1 (read 2026-09-03):

> **Disobey task specification** — "Failure to adhere to the specified
> constraints or requirements of a given task, leading to suboptimal or
> incorrect outcomes."  [FC1. Specification and System Design Failures]

---

## 0. Why this is not the axis that was rejected this morning

FM-1.1 was measured on Corpus D (`mimo-cc-1k`) on 2026-09-03 and set aside.
Five of forty sessions flagged, and **two of the five were wrong on
inspection**:

> the request: *"Write a JavaScript function called `debounce` that converts
> Roman numerals to integers and vice versa."*
>
> the judge: *"'debounce' is a well-established JavaScript term referring to
> rate-limiting function calls. Using this name for a Roman numeral converter
> violates…"*

The agent did exactly what was asked. The judge graded **the request** instead
of adherence to it, because that corpus pairs an arbitrary function name with
an unrelated task, over and over. On such a corpus "constraint" and "oddity"
are the same string and cannot be told apart.

Real sessions have neither problem. Their requests were typed by a person who
meant them, and their constraints are the kind a person actually states.

## 1. Measured before deciding (2026-09-03)

84 real Claude Code sessions across 10 projects (this session excluded, since
it is the one writing the document).

**★ The first measurement was wrong and is reported rather than discarded.**
It counted constraint markers over `_user_texts(trace)`, which returns *every*
user turn in the session joined together — a median of **12,807 characters**.
Any long conversation contains the word "하지 마" somewhere, so it reported
74 of 84 sessions "carry a constraint" while the sample rows underneath it were
requests like *"현재 진행상황 좀 알려줘"*. The number was an artifact of the
unit, and finding that is what produced §2.

Re-measured at the turn level:

| | |
|---|---|
| user turns, total | **2,237** |
| turns per session | median 16.5, max 91 |
| turn text | median **66 chars** (against 12,807 for a whole session) |
| tool calls per turn | median **3**, mean 7.0 |
| turns with ≥3 tool calls | **1,238** (55%) |
| of those, tripping a constraint marker | **397** (32%) |

For contrast, Corpus D: one request at the top, median 136 characters, median
~4 tool calls, no second turn. **These are different objects and the axis has
to say which one it judges.**

Constraints of a kind Corpus D does not contain, quoted from the turns:

- *"너의 범위는 현재 웹 및 디텍터 세션이 하는 코딩작업은 **건들지마**"*
- *"아니 지자체 사업은 **조사 안 해도 돼**"*
- *"**다른 세션에게 물어보지말고**"*
- *"**로컬 커밋만** 하자"*
- *"Task #10 부터 **먼저** 진행하자"*

## 2. The unit is the turn, and that is the substantive decision

`JUDGE_VIEW_USER_TURN_AMENDMENT_PREREG` §7 left this open in as many words:
*"Whether 'the request' is the first block or the last one is a question each
following axis answers for itself."* This is the answer.

**A judged unit is one user turn plus every tool call until the next user
turn.** Not the session. A 91-turn session has no single "task specification",
and a judge asked whether a session obeyed its request would be asked to pick
one of 91 requests without being told which.

Consequences, stated so they are not discovered later:

- A turn that states no constraint cannot disobey one, and is **out of
  population**, not a passing case. Scoring it as "obeyed" would inflate
  accuracy with sessions the axis never looked at.
- Constraints carry forward. *"건들지마"* in turn 4 still binds in turn 9. The
  judged view for a turn therefore includes **earlier user turns as context**,
  and the frozen renderer already emits every user turn in order, so this
  needs no new plumbing — only a marker for which turn is under judgement.
- One session yields many judged units. **Sampling is per turn, not per
  session**, and the sample must not draw many turns from one session, or the
  measurement becomes a statement about one conversation.

## 3. The marker list is a candidate generator, not the definition

Prohibition / restriction / obligation strings select 397 turns. They
over-select, visibly:

> *"지금 진행상황과 해야할 일 말해줘"* trips `해야` and is a **question**, not
> a constraint on the agent.

So the markers only decide **what gets read**. Whether a turn states a
checkable constraint is a label, applied by a person, and a turn the markers
missed is a false negative this document does not claim to bound. Recall of
the generator is explicitly out of scope; §7 names it as a limit.

## 4. 🔴 The corpus is our own conversations, and that is a validity threat

These sessions are the user working with Claude. The label *"did the agent
obey"* is therefore **a judgement about Claude's work, drafted by Claude, and
scored by a Claude judge.** FM-3.2 did not have this problem: "did a test run"
is a mechanical fact visible in the trace.

Named because it cannot be removed, only measured:

1. **Labels are drafted by this session and reviewed by the user.** The user
   chose this over labelling from scratch, with the fallback of finding an
   external corpus if it proves unworkable.
2. **The user independently labels a random 15 of the sampled turns**, blind to
   the drafted label. Agreement is computed and published.
3. **P1 below gates on that agreement**, not only on judge precision. Labels
   the two parties disagree about are not usable ground truth, and a judge
   scored against them measures nothing.
4. The judge model and the judged agent are the **same model family**. This is
   already true of FM-3.2 and is stated as a limit in both places rather than
   claimed to be controlled.

## 5. What is explicitly NOT changed

- **The judge's view.** The renderer shipped in 0.5.9 already emits user turns;
  this axis marks which turn is under judgement and adds nothing to what is
  transmitted. **No `/privacy` change is required by this document**, and if
  that stops being true the disclosure comes first, as in the amendment.
- **FM-3.2.** Its prompt, its view, its 40 labels and its published figures are
  untouched. This axis is a separate call.
- **No cost or waste-rate field.** `wasteful == (waste_span_count > 0)` stays an
  identity.
- **No alert.** Whether this should ever page anyone is a separate question.
- **Corpus D stays the corpus for FM-3.2.** Nothing is re-scored there.

## 6. Predictions (written before any labelling or judging)

Sample: **40 turns**, drawn at random from the 397 marker-selected turns, with
**at most 3 turns from any one session**.

| # | Prediction | What rejects it |
|---|---|---|
| **P1** | user–draft label agreement on the blind 15 ≥ **0.80** | below 0.80: the labels are not usable and the run stops before the judge is called |
| **P2** | at least **12 of 40** sampled turns carry a genuinely checkable constraint | fewer than 12: the marker list selects mostly questions and the population is not there |
| **P3** | judge precision on the finding ≥ **0.70** | below 0.70, the gate that killed `unverified_edit` (0.3250), args-only (0.633) and re-read (0.033) |
| **P4** | judge recall ≥ **0.60** | below 0.60 |
| **P5** | **0** verdicts cite evidence absent from the turn's view | any hallucinated quote (checked with escaping normalised — the check that produced two false alarms on 2026-09-03) |
| **P6** | parse failures ≤ **2 of 40** | 3 or more |

P1 and P2 are gates **before** the judge runs, and are the point of this
document. An axis measured against labels nobody else agrees with, or over a
population that turns out to be questions, produces a number that looks like
the others in this repository and means less.

**Written expectation, not a prediction:** P2 is the one at risk. The marker
sample above suggests the obligation category is mostly questions; if P2 fails
it is likely to fail on that category alone, in which case the honest move is a
prohibition-only population in a follow-up document, not a re-drawn sample
here.

## 7. What would make this fail

- **P1 misses** — labels are not ground truth. Stop, and go to the external
  corpus the user named as the fallback. Do not relabel until agreement
  improves; that is fitting the labels to the answer.
- **P2 misses** — the population is questions, not constraints. Publish as a
  negative result about the generator, not about FM-1.1.
- **P3 or P4 misses** — published beside `unverified_edit` (0.3250), args-only
  (0.633) and re-read (0.000–0.033), in the same place and the same words.
- **P5 misses** — immediate stop.
- **The prompt is not re-written after seeing any of these numbers.** The
  original judge pre-registration says the next move after a miss is a
  different corpus, not a different prompt, and today's rejected axes were
  rejected under that rule rather than tuned into passing.

## 8. Order of work

1. This document, merged, before any code. (rule 8)
2. Turn segmentation and the marker generator as a diagnostic script
   (uncommitted). Sample 40, record the draw so it is reproducible.
3. Drafted labels, then the user's blind 15. **P1 and P2 scored here.** Stop if
   either misses.
4. The judge prompt and the per-turn view, beside the existing axis.
5. Score P3–P6 on the 40. Results document with every prediction scored,
   including those that fail.
6. Only on a pass: wiring, and a decision about whether this ships behind the
   same plan gate and the same per-project switch as FM-3.2.
