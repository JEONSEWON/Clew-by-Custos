# FM-2.2 on real sessions: it went ahead instead of asking

Rule 8: merged before any code. Nothing here is implemented.

FM-2.2, verbatim from arXiv 2503.13657 v1 HTML (read 2026-09-03):

> **Fail to ask for clarification** — "Inability to request additional
> information when faced with unclear or incomplete data, potentially resulting
> in incorrect actions."  [FC2. Inter-Agent Misalignment]

🔴 **A declared deviation, up front.** FC2 is *inter-agent* misalignment, and a
Claude Code session has one agent. What this document judges is the
**human–agent** pair: a person's request was incomplete and the agent acted
anyway. The definition itself names neither agents nor humans — it names
unclear or incomplete data — so the transfer is defensible, but it **is** a
transfer and every result carries it. FM-2.4 and FM-2.5 are not transferable
this way and are out of scope here.

---

## 0. Why this axis and not the six that were set aside

Six axes were examined before this one and none reached a pre-registration:

| axis | why it stopped | which side was empty |
|---|---|---|
| FM-3.3 | 6 verification-command errors in 14,211 tool calls | real sessions |
| FM-1.5 | idempotent candidates **0 / 88 sessions** | real sessions |
| FM-2.6 | reasoning is **1.8%** of the judge's view | the material |
| FM-2.3 | **1 / 40** candidates | real sessions |
| FM-3.1 | benchmark 37/1017 (3.6%) vs real sessions **0 / 85** | real sessions |
| FM-1.1 | 18/40 constrained, **0 violations** (both labellers) | the positive class |

Every one of them failed on the same side: *the phenomenon was not in the
traces we hold.* Each was found by drawing a random sample from a corpus we
already had and re-measuring. **This document inverts that order** — the
population was counted first, on both sides, and the axis was chosen because
both counts came back non-empty.

## 1. Measured before deciding (2026-09-03)

### 1.1 The label side: MAST-Data, on the revision the shipped figures name

`mcemri/MAST-Data`, CC-BY-4.0. Per-failure-mode marks exist for all 14 modes on
all 1,642 traces. FM-2.2 is marked on **265 of 1,642 (16.14%)**.

🔴 **The first census of this was wrong, and the cause generalises.** The
machine's Hugging Face cache is pinned at revision `5a82e32` (2026-06-02),
which holds **1,242** rows. The published revision is `95118ac` (2026-08-13)
with **1,642**. Read from the stale cache, FM-2.5 has **0** positives; read
from the current file it has **370**. A stale cache does not fail — it answers,
and its answer is "the data is not there", which is the same sentence six axes
have already been rejected with.

The current file was fingerprinted against the numbers
`VERIFICATION_JUDGE_RESULTS.md` §7 already publishes, and all three match:

| | expected (shipped doc) | measured |
|---|---|---|
| rows | 1,642 | **1,642** |
| AG2 + MetaGPT subset | 1,027 | **1,027** |
| subset median trajectory chars | 6,117 | **6,117** |

So the 2026-08-31 second-corpus run read the current revision and **its
published description is accurate.** Only today's re-census had to be redone.
The fingerprint assertion stays in the diagnostic
(`_mast_positive_census.py`) so a stale read cannot pass silently again.

★ **Their marks are not ground truth** — their README says an LLM judge
produced them. They size the labelling pool and settle nothing, exactly as in
FM-3.2 step 5.

### 1.2 The real side: does the agent ever ask?

85 real Claude Code sessions (this session excluded — it is the one writing the
document). Turn segmentation and the user-authored test are the ones
FM-1.1 §2 and §6 fixed, machine-authored `user`-role text excluded.

| | |
|---|---|
| turns, total | **2,262** |
| turns, user-authored | **1,777** |
| **stopped and asked** | **144 (8.10%)** — in **45 of 85** sessions |
| ↳ via `AskUserQuestion` | 48 (2.70%) |
| ↳ text question, no tool call | 96 (5.40%) |
| asked *after* acting | 193 (10.86%) |
| did not ask | **1,440 (81.04%)** |
| user text length | **<50 chars: 1,012** · 50–199: 424 · 200+: 341 |

**This is the first axis where both sides are populated.** 144 turns where the
agent stopped and asked, 1,440 where it did not, and a majority of requests
short enough to be incomplete.

## 2. The unit is the turn

Inherited, not re-decided: FM-1.1 §2 established the turn as the unit on this
corpus, because a session has a median of 16.5 turns and a median turn text of
66 characters — there is no single "the request" to judge a session against.
A request that was incomplete was incomplete **when it was made**.

## 3. The candidate rule, and why it is not degenerate

> **candidate** = the agent did not ask, **and** the user's turn is under 50
> characters, **and** the agent made at least one tool call.

Measured: **618 turns in 73 sessions** (at most 26 from any one session).

Shortness is a *generator*, not the definition — the same relationship the
marker list has to FM-1.1 (§3 there). A short request can be perfectly
complete (*"머지해줘"*), and a long one can be missing the one fact that
matters. The judge decides; this rule only decides what gets read.

The crosstab that says the rule is not circular:

| asked? | <50 chars | 50–199 | 200+ |
|---|---:|---:|---:|
| `AskUserQuestion` | **25** | 9 | 14 |
| text question, no action | 65 | 23 | 8 |
| asked after acting | 127 | 44 | 22 |
| did not ask (acted) | **618** | 248 | 198 |
| did not ask (no tools) | 177 | 100 | 99 |

★ **On short requests the agent asks 25 times with the tool and 65 times in
text.** "Short request → always proceeds" is false, so the candidate rule is
selecting a behaviour rather than restating an artifact of length.

## 4. 🔴 Two validity threats, stated before the result

- **The corpus is our own conversations.** Same threat FM-1.1 §4 carries. The
  person typing these turns is the person who will read the result, and the
  agent's asking behaviour was shaped by this repository's own instructions
  ("모호한 부분은 추측하지 말고 반드시 질문"). Our ask-rate is therefore
  **not** a population estimate for anyone else's sessions, and no published
  figure will claim it is. It is used here only to establish that both classes
  exist.
- **The ask surface is not constant across sessions.** `AskUserQuestion` is a
  harness tool; a session recorded before it was available cannot use it, so
  part of "did not ask" is tooling, not choice. The text-question surface (96
  turns, 5.40%) exists in every session and is why the ask-rate is not read
  from the tool alone. **The sample draw records, per turn, whether the tool
  appears anywhere in that session**, so this can be checked against the labels
  rather than assumed away.

## 5. What is explicitly NOT changed

- **The judge's view.** 0.5.9 already renders user turns; this axis marks which
  turn is under judgement. **No `/privacy` change is required by this
  document.** If that stops being true, the disclosure ships first — and the
  web session is notified before, not after.
- **FM-3.2 and FM-1.1.** Their prompts, views, labels and published figures are
  untouched. This is a separate call.
- **No cost or waste-rate field.** `wasteful == (waste_span_count > 0)` stays
  an identity.
- **No alert.** Whether this should ever page anyone is a separate question.
- **The detector name freeze.** No detector is renamed by this document.

## 6. Predictions (written before any labelling or judging)

Sample: **40 candidate turns** drawn from the 618 with `random.Random(20260903)`,
**at most 3 from any one session**. Plus **40 contrast turns** drawn the same
way from the 144 stop-and-ask turns — judged, **not** hand-labelled.

| # | Prediction | What rejects it |
|---|---|---|
| **P1** | user–draft label agreement on a blind **15** ≥ **0.80** | below 0.80: the labels are not usable and the judge is not called |
| **P2** | 🔴 **at least 8 of 40** candidates hand-labelled positive ("the request was incomplete in a way that mattered, and it did not ask") | fewer than 8: **stop.** The axis is unmeasurable here even if the judge is perfect — see below |
| **P3** | judge precision on the finding ≥ **0.70** | below 0.70, the gate that killed `unverified_edit` (0.3250), args-only (0.633) and re-read (0.033) |
| **P4** | judge recall ≥ **0.60** | below 0.60 |
| **P5** | judge flag rate on the 40 candidates minus flag rate on the 40 contrast turns ≥ **+20 pp** | under +20pp the judge is not reading the request — it flags regardless of whether the agent asked |
| **P6** | **0** verdicts cite evidence absent from the turn's view (escaping normalised) | any hallucinated quote |
| **P7** | parse failures ≤ **2 of 80** | 3 or more |

**P2 is the prediction that was missing from FM-1.1, and its absence is why
that axis nearly reached a judge with an empty positive class.** With zero
positives a judge that never flags scores perfect precision and one that flags
anything scores zero, and the document passes both. The floor is 8 rather than
a token 1 because below roughly eight positives a single label change moves
precision by more than 0.10, which is wider than the gap between a pass and a
kill at P3.

**Written expectation, not a prediction:** P2 is again the one at risk, for a
new reason. This repository instructs the agent to ask when unsure, and the
ask-rate above (8.10% of turns, 45 of 85 sessions) may be high *because* of
that instruction. If P2 misses, the honest reading is that our corpus is a
**hard negative** case for FM-2.2, and the follow-up is an external corpus —
not a re-drawn sample here.

## 7. What would make this fail

- **P1 misses** — labels are not ground truth. Stop. Do not relabel until
  agreement improves; that is fitting labels to the answer.
- **P2 misses** — publish as a negative result about this corpus, naming the
  instruction-to-ask as the likely cause, and take FM-2.2 to an external
  corpus. Do **not** widen the candidate rule to find positives.
- **P3, P4 or P5 misses** — published beside `unverified_edit` (0.3250),
  args-only (0.633) and re-read (0.000–0.033), in the same place and words.
- **P6 misses** — immediate stop.
- **The prompt is not re-written after seeing any of these numbers.** After a
  miss the next move is a different corpus, not a different prompt.

## 8. Order of work

1. This document, merged, before any code. (rule 8)
2. The candidate generator and the draw as diagnostics (uncommitted):
   `_fm22_clarification_prevalence.py`, `_fm22_candidate_pool.py`. The draw is
   recorded so it is reproducible, and §1/§3 counts must reproduce from it
   before anything else runs.
3. **Draft labels written to a file and frozen first**, then the user's blind
   15. **P1 and P2 scored here. Stop if either misses.** (2026-09-03: doing
   this in the other order cost 15 contaminated labels.)
4. The judge prompt and the per-turn view, beside the existing axes.
5. Score P3–P7 on the 80 calls. Results document with every prediction scored,
   including those that fail.
6. Only on a pass: wiring, and a decision about whether this ships behind the
   same plan gate and the same per-project switch as FM-3.2.

## 9. Cost, for planning rather than as a claim

FM-3.2 measured $0.0046 and 1.8 s per session on `claude-haiku-4-5`. 80 calls
on turn-sized views is well under that per call. Nothing here is priced for a
customer, and the axis stays opt-in on the user's own key.
