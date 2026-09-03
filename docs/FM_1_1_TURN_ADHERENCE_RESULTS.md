# Results: FM-1.1 has no positive class on our own sessions

Scores `FM_1_1_TURN_ADHERENCE_PREREG.md`. Run 2026-09-03, the day the
pre-registration was merged.

**The axis is not measurable here. Zero violations in forty labelled turns,
agreed by both labellers.** Precision and recall of the finding are undefined,
so P3 and P4 cannot be scored at all — not failed, undefined.

---

## 0. What was scored

| # | prediction | result | |
|---|---|---|---|
| P1 | user–draft agreement ≥ 0.80 on the blind set | **partial** — the user answered Q2 (0 violations) for all 15 and did not answer Q1 per item, so agreement on "is there a constraint" is unmeasured | not scorable as written |
| P2 | ≥ 12 of 40 turns carry a checkable constraint | **18 of 40** | PASS |
| P3 | judge precision ≥ 0.70 | **undefined** — no positive labels exist | not run |
| P4 | judge recall ≥ 0.60 | **undefined** — 0/0 | not run |
| P5 | 0 hallucinated evidence | not run | — |
| P6 | parse failures ≤ 2 | not run | — |

**No judge call was made.** The gates that fire before the judge did their job:
P2 passed, and the labelling stage produced an empty positive class, which
stops the run under §7 rather than spending on a measurement that cannot mean
anything.

## 1. 🔴 The pre-registration had a hole, and this is it

Six predictions, and **not one of them required a minimum number of positive
labels.** FM-3.2's set had 13 positives in 40, so the question never came up
and I did not think to ask it.

A precision of "the finding" needs findings to be right or wrong about. With
zero, any flag the judge raises is a false positive by construction, and a
judge that never flags scores perfectly on nothing. Both outcomes are
meaningless, and the document as written would have accepted either.

**What should have been there:** a prediction like *"at least 5 of the 40
labelled turns show a violation; below that the axis is not measurable on this
corpus and no judge is called."* That is now written down for the next axis
rather than discovered again.

## 2. What the zero does and does not say

**It does not say agents obey instructions.** Two things push the count toward
zero and neither was controlled:

1. **The labelling rule was conservative by construction.** "Not visible in the
   recorded actions" was defined as *not broken*. A constraint violated in
   something the agent said, or by something it quietly did not do, scores as
   obeyed.
2. **The action list truncates at 25.** A turn with 54 actions was labelled
   from its first 25. A violation in the tail is invisible to the label.

Both were chosen to keep labelling feasible for a person, and both bias the
same way. The honest statement is narrow: **under a conservative rule and a
truncated view, no violation was visible in 40 turns.**

**It does say the axis cannot be measured this way on this corpus**, which is
the decision the document existed to reach.

## 3. Two labellers, and what the second one actually settled

The first blind pass was contaminated by an ordering defect of mine: the user
answered before I had committed my own labels, so my subsequent labels were
anchored. That is recorded in `_fm11_labels_drafted.json` per item.

The fix was a second blind set of 15 drawn from the 25 turns the user had not
seen, with my labels committed to a file first (seed 202609032, recorded). The
user's answer on that set was again **zero violations**.

So the zero is not an artifact of the ordering defect: it reproduces on a set
where the ordering was correct. That is the one thing the redo established, and
it is worth the extra pass.

What it did **not** establish is Q1 agreement — the user answered the violation
question and not the constraint question. P1 stays unscored, and if this axis is
ever retried the label sheet has to force both answers rather than accept one.

## 4. Where the population came from, and one trap inside it

84 real Claude Code sessions, 10 projects, 2,237 user turns. Population after
filtering: **215** turns with ≥3 tool calls that state a constraint marker.

★ **Machine text arrives under the `user` role in more shapes than one.** The
0.5.9 renderer already excludes `tool_result` blocks; that was not enough. The
first population of 397 turns was **44.8% cross-session messages** — text
written by another Claude session and delivered as a user turn — against 11.7%
across all turns.

The generator was preferentially selecting the agent's own prose, because those
messages are long, technical, and full of "하지 마", "만", "반드시". Excluding
them is conformance with §2's "one user turn", not a threshold moved after
seeing a number: no label had been assigned and no judge had been called.

Pasted material the person forwarded — emails, another session's output — was
**not** filtered out. It is user-authored in the only sense that matters, and it
labels as "no constraint", which is what P2 is for. Filtering further would have
been shaping the sample until it looked right.

## 5. What happens next

Three axes were examined on 2026-09-03 and all three are blocked, each for a
different reason. Naming them separately matters, because "we need more data"
is only true of one:

| axis | why it stopped | is it a data shortage? |
|---|---|---|
| FM-2.3 task derailment | 1 candidate in 40 | **yes**, of a kind: short single-task sessions leave nothing to derail from |
| FM-3.1 premature termination | 37/1017 on the benchmark corpus, **0/85 on real sessions** — it measures how the dataset was built | **no**, a corpus artifact |
| FM-1.1 disobey task specification | 18 constraints, **0 violations** | **no**, an empty positive class |

The next attempt should start from a corpus **selected for containing
failures**, not from one selected for being available. `mcemri/MAST-Data`
carries per-type labels produced by an LLM judge — unusable as ground truth,
and the README says so, but usable to **find candidates worth hand-labelling**.
That inverts today's order: find the positives first, then measure, rather than
sampling at random and discovering the class is empty.

That is a separate pre-registration and is not started here.
