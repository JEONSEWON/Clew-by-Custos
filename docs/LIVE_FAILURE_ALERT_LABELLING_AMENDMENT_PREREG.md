# Live Failure Alert, Labelling Amendment (Pre-registration)

**Status.** Amendment to
[`LIVE_FAILURE_ALERT_PREREG.md`](LIVE_FAILURE_ALERT_PREREG.md) §6 P3 and §8
step 4. Per `feedback_rule_8` this is pushed before the labelling it changes.
§2, §5 and §6 are frozen positions. The rejected P1 in
[`LIVE_FAILURE_ALERT_RESULTS.md`](LIVE_FAILURE_ALERT_RESULTS.md) stands as
published; nothing here edits it.

---

## 0. The gate cannot be reached from where it was pointed

P3 requires precision on **30 hand-labelled shadow findings**, and shadow mode
produces one finding per session. Measured on this machine:

| | |
|---|---|
| sessions, 2026-08-02 to 08-31 | 87 over 29 days = **3.0 a day** |
| findings the watcher records over that corpus | **7** |
| rate | **0.24 a day** |
| time to 30 | **124 days** |

That is the gate's real cost as written, and it was not visible when the
document was written because the finding rate had not been measured yet.

**And the obvious substitute does not work.** Corpus D
(`mimo-claude-code-traces-1k`, 859 traces) is Claude Code data and it is
already here, but its sessions are short: **244 traces have 1–2 tool spans, 337
have 3–5, and only 60 have 11 or more**
([`WASTE_RATE_CORPUS_D_MIMO_CC_RESULTS.md`](WASTE_RATE_CORPUS_D_MIMO_CC_RESULTS.md)
§3). The first repeat candidate on this machine's corpus appears at a **median
of 98 tool calls** (min 9). A corpus whose median session is four tool calls
cannot produce many findings, and §5 predicts it produces almost none.

## 1. What is actually scarce

Not the signal. The **alert** is scarce, because §3.2 caps it at one per
session — deliberately, so a session with 24 candidates does not send 24 mails.

The 7 sessions that fired hold **21 confirmed pairs** between them
(1, 1, 1, 3, 3, 3, 9). The cap throws 14 of them away for delivery, and the
labelling inherited that throw-away by counting findings instead of pairs.

**A delivery cap is not a measurement unit.** What a labeller judges is "is this
confirmed repeat really repeated work", and that question has 21 instances here,
not 7.

## 2. The change

**The labelling unit becomes the confirmed pair, and two numbers are reported
instead of one.**

| | unit | n | role |
|---|---|---|---|
| **signal precision** | confirmed repeat pair | 30 labelled | **the gate.** ≥ 0.70 opens delivery |
| **alert precision** | the first confirmed pair of a session — what would be sent | all available | **reported, no gate**, with its interval |

Pairs are drawn from the same code path (`live.first_confirmed` and the
cascade behind it) over Claude Code corpora: this machine's sessions, Corpus A
(trace-commons, 28 real sessions), and Corpus D. Sampled with
`random.Random(20260902)` across the pooled set, stratified by source corpus so
one source cannot supply the whole sample.

Why the pair is the right unit for the gate: the alert's claim is *"this
session is repeating work"*, and every confirmed pair is one instance of that
claim being true or false. Labelling only the first pair measures the same
predicate on a smaller sample chosen by arrival order.

Why alert precision is still reported: the first pair is what a person receives,
and if it behaves differently from the rest that has to be visible rather than
averaged away.

## 3. What is explicitly NOT changed

- **The gate value.** 0.70, the same number for the same reason as re-read
  (0.000–0.033), args-only (0.633) and `unverified_edit` (0.3250).
- **The trigger and the caps.** One alert per session, three per project per
  hour. §3.2 stands.
- **Shadow mode.** Nothing is sent. Delivery is still §8 step 6 and still its
  own decision after the gate.
- **The detection.** φ, N, `confirm_pair`, the earliest-pair rule.
- **The rejected P1.** 7 findings against a predicted 32, published.

## 4. What this costs in honesty

Corpus A and Corpus D are not this machine's traffic. A precision measured on
pooled corpora is a statement about the signal, not about what one person's
week looks like. **The results will say which corpus each labelled pair came
from and report precision per corpus as well as pooled**, so a reader can see
whether the number survives the split.

When live shadow findings reach 30 on their own, the gate is re-run on them and
that result is published next to this one.

## 5. Predictions

| # | Prediction | What rejects it |
|---|---|---|
| **P1** | Corpus D, all 859 traces, yields **fewer than 10** confirmed pairs | 10 or more — then short sessions repeat more than §0's arithmetic says and the reasoning there is wrong |
| **P2** | Corpus A, 28 sessions, yields **at least 20** confirmed pairs | fewer than 20 |
| **P3** | the pooled pool (this machine + A + D) reaches **at least 40** confirmed pairs, so 30 can be sampled with room to spare | fewer than 40 |
| **P4** | **signal precision ≥ 0.70** on the 30 labelled pairs | below 0.70 |
| **P5** | **alert precision is within 0.15 of signal precision** — the first pair is not a different animal | a gap wider than 0.15 |
| **P6** | no corpus's own precision is below **0.50** | any corpus below it, which would mean the pooled figure is carried by one source |

Labels are committed before precision is computed, as in the `unverified_edit`
run. P4 is the gate; P1 is the prediction this document's own reasoning stands
on.

## 6. What would make this fail

- **P3 misses**: stop. There is no sample and the gate waits for live data,
  124 days or however long it takes.
- **P4 misses**: the signal stays in shadow permanently and the false-positive
  rate is published. It does not ship at a lower gate.
- **P5 or P6 miss**: the pooled number is not reportable as one figure. Report
  the split and do not open delivery on the pooled value.
- **P1 misses**: harmless to the plan and worth knowing — Corpus D would then
  be a usable source and §0's session-length reasoning needs revisiting.

## 7. Order of work

1. This document, pushed before any labelling. (rule 8)
2. Extract the pooled pairs. P1, P2, P3 measured. Stop if P3 misses.
3. Sample 30, label them, **commit the labels before computing anything**.
4. P4, P5, P6 computed and published whether they pass or not.
5. Delivery remains a separate decision after that, unchanged.
