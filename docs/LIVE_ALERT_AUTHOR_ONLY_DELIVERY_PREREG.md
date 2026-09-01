# Live Alert, Author-Only Delivery (Pre-registration)

**Status.** Opens the delivery that
[`LIVE_FAILURE_ALERT_PREREG.md`](LIVE_FAILURE_ALERT_PREREG.md) §3.3 left closed,
to **one project only**. Per `feedback_rule_8` this is pushed before the code.
§2, §3, §5, §7 and §8 are frozen positions.

---

## 0. The gate passed and the thing it was gating was never measured

[`LIVE_ALERT_IDEMPOTENT_TRIGGER_RESULTS.md`](LIVE_ALERT_IDEMPOTENT_TRIGGER_RESULTS.md)
scored **0.9667** against a raised gate of 0.85, with no source below 0.70.

It does not open delivery, and §3.3 of the original document says why in a
clause that has been read past twice:

> Delivery opens only when §6 P3 is met **on hand-labelled live findings**.

Every pair labelled so far came from **batch analysis of finished sessions**.
The watcher confirms the same pairs with the same function, and that is an
argument, not a measurement. **The live path has never produced a finding that
anybody labelled**, because it has never produced a finding at all:

```
watcher runs today                 832
findings recorded                    0
sessions with a confirmed pair
  on this machine, all time          6 of 87
```

Repeats are rare, and the restriction to idempotent tools made them rarer. The
earlier estimate of 0.24 findings a day is now an overestimate.

**So waiting does not work.** 8 real-session pairs is the sample the corpora
contain, its interval is [0.4735, 0.9968], and the way to widen it is not
patience — at this rate 30 live findings is months, during which the feature
does not exist.

## 1. What this document does instead

**Opens delivery for one project: the author's.** Nothing else changes.

Not because the risk is acceptable in general — the interval says it is not
established — but because the risk lands on the person who wrote it, and
because **the only remaining way to get live findings is to receive them.**

Three things follow that are worth stating separately:

1. **The delivery path itself has never run.** Precision is not the only
   untested thing. An endpoint that takes a client-asserted finding, a mail
   that a person actually receives, the caps holding against a live watcher —
   none of that has been exercised, and none of it is measured by labelling
   batch pairs.
2. **Each alert is a labelled sample.** The recipient knows whether the finding
   was right. §3 makes that a recorded answer rather than an impression, so the
   thing that was too slow to accumulate accumulates as a side effect of use.
3. **A wrong alert costs the author a minute.** That is the correct place for
   this uncertainty to sit while it is uncertainty.

## 2. Scope, as a mechanism rather than a promise

**One project id, in server configuration, not in the client.**

The endpoint refuses to send for any project not on an allow-list it reads at
call time. A client that asserts a finding for another project gets its finding
recorded and no mail. That is the §5 risk of the original document — *"the
server will email what a client asserts"* — answered by not letting the client
choose who is in the experiment.

**Not** a flag in `clew.yaml`, **not** a build-time constant, **not** a check in
the watcher. All three would let a second project into the experiment by
editing the wrong file.

## 3. The feedback that makes an alert a sample

Every mail carries two links: **"this was real"** and **"this was not"**.

They write a labelled row keyed by `(project, session, signal)` — the same key
§3.2 caps on, so a label cannot be double-counted. Nothing else is collected:
no path, no free text, no trace.

★ The label is **the recipient's**, and the recipient is the author. It is
therefore one labeller, unblinded, judging a system he built. That is the worst
labelling arrangement this project has used and it is chosen deliberately: the
alternative is no labels. §7 requires it to be reported that way and forbids
pooling it with the hand-labelled 30, which were at least blind to the outcome.

## 4. What is explicitly NOT changed

- **The trigger.** Idempotent-only, first confirmed pair, one per
  `(session, signal)`, three per project per hour. Unchanged.
- **The detection.** φ, N, `confirm_pair`, the earliest-pair rule.
- **Every stored figure**, every waste rate, every published number.
- **The slow path.** The cost-cap alert keeps its own cadence and its own mail.
- **Shadow for everyone else.** Every project not on the allow-list behaves
  exactly as it does today: recorded locally, nothing sent.

## 5. What this costs, said plainly

**A person will receive a wrong alert.** At the measured 0.9667 that is about
one in thirty; at the interval's lower bound it is one in two. Both are
possible and the sample cannot tell them apart.

**And the server will send a mail because a client said so.** The endpoint
takes a finding, not a trace. It is bounded by the key, by the allow-list, by
the caps, and by the payload being one enum with counts — and none of those
bounds make the assertion true. A client with a valid key can cause a mail to
its own project's address by asserting something false. That is the shape of
the risk and it does not go away by scoping the experiment.

## 6. Predictions

| # | Prediction | What rejects it |
|---|---|---|
| **P1** | a live finding on the author's machine produces exactly **one** mail, and a second finding on the same `(session, signal)` produces **none** | any other count |
| **P2** | a finding asserted for a project not on the allow-list is **recorded and not sent** | a mail |
| **P3** | server analyses caused by delivery: **0** — the endpoint takes a finding and never a trace | any |
| **P4** | ten concurrent findings in one project in one hour produce **3** mails | any other count |
| **P5** | **20 live findings are labelled** within 60 days of switching on | fewer — and then the accumulation argument in §0 was wrong in the other direction too |
| **P6** | live precision, on those labels, is **within 0.20 of 0.9667** | a gap wider than 0.20, which would mean batch pairs do not stand in for live findings and the whole labelling route needs redoing |

P6 is the one this document exists to answer. P3 is the design constraint that
made the two-path split necessary and it is a count, not a judgement.

## 7. What would make this fail

- **P2 or P4 misses**: stop and revert to shadow. A cap that does not hold is
  the difference between an alert and a mailing list, and this opens on the
  premise that the caps are what make one recipient safe.
- **P3 misses**: stop. A fast path that costs server analyses is the slow path
  with extra steps, and §1 of the original document says the whole split exists
  for that.
- **P6 misses**: the batch-labelled 0.9667 does not describe the live path.
  Delivery closes and the gate is re-derived from live findings only.
- **P5 misses**: not a stop. It means live findings accumulate even more slowly
  than §0 measured, and the honest report is that this axis cannot be validated
  on one machine's traffic at all.
- **A wrong alert that the author cannot explain**: reported as a case, in the
  results, with the pair. One in thirty is the expectation, not a surprise.

## 8. Order of work

1. This document, merged, before any code.
2. The endpoint, the allow-list and the feedback links, with tests. P1–P4
   measured before it is switched on for anything.
3. Switched on for one project. Findings and labels accumulate.
4. P5 and P6 measured at 60 days and published whether they pass or not.
5. Widening beyond one project is a separate decision after that, and it is not
   implied by this document passing.
