# Session Close Rule — Latency Amendment (Pre-registration)

**Status.** Amendment to `docs/SESSION_CLOSE_RULE_PREREG.md`, whose R1 threshold
(240 minutes) is frozen there. Per `feedback_rule_8` this document is pushed and
PR-opened **before any code, schema, or measurement change lands**. The rule,
the predictions in §6 and the rejection conditions in §7 are frozen positions.
Adjusting them after seeing results is not allowed.

---

## 0. What is wrong

A session is submitted only after it has been quiet for four hours. Adding the
rest of the chain, the worst case from "the waste happened" to "a person is
told" is:

| step | delay |
|---|---|
| session must go quiet (`CLOSE_AFTER` = 240 min) | 4 h |
| unattended sweep runs hourly at `:02` | up to 1 h |
| rollup aggregates at `:05` | up to 1 h |
| rules evaluate at `:20` / `:35` | up to 30 min |
| delivery at `:50` | up to 15 min |
| **total** | **≈ 6 h 45 min** |

For a leak, telling someone late still helps: the pattern repeats every run, so
catching it after run 1 saves runs 2 through 1000. For a **failure**, it does
not. A failed task ends inside its session, and a notice six hours later is
about something nobody can act on any more.

This matters now because the product's direction is failure *and* cost together
(`feedback_failure_and_cost_are_one`), and the first extension planned is
verification failure. Building failure detection on a 6-hour pipe would ship a
detector whose output arrives after it is useful.

## 1. Why the four hours exist

`SESSION_CLOSE_RULE_PREREG` §2 states the reason exactly: session files grow by
appending, and sending a grown file again is not caught downstream.

- `run` is unique on `(project_id, trace_id, payload_sha256)`.
- A grown file has different bytes, so a different `payload_sha256`, so the
  constraint does not fire.
- Both rows then aggregate into `rollup_hourly`, and the waste in the first half
  of the session is counted twice.

The four hours are not a measurement of when a session is finished in any deep
sense. They are how long you must wait for "it will not grow again" to be true
often enough. §3.2 of the original measured that: at 240 minutes, 2 of 84
sessions resumed afterwards.

**So the threshold is a workaround for a uniqueness rule, not a property of
sessions.** Change what makes a resubmission safe and the wait can shrink.

## 2. The change

**Make a session's row unique per analysis parameters, and replace it on
resubmission.**

```
unique (project_id, trace_id, payload_sha256)      -- current
unique (project_id, trace_id, params_key)          -- proposed
```

`params_key` is already a stored generated column, `md5(phi : n_window :
embed_model : analyzer_version)`. Keeping it in the key preserves the
comparability guard that exists today: a trace analysed under different
detector parameters stays a separate row and never silently overwrites a
measurement taken under different rules.

`ingest_run` becomes an upsert on that key. Resubmitting a session that has
grown replaces its row with the newer, longer analysis rather than adding a
second one. Double counting becomes structurally impossible instead of being
avoided by waiting.

With that in place `CLOSE_AFTER` no longer has to cover "will it grow again".

**Proposed: `CLOSE_AFTER` 240 min → 20 min.** New worst case:

| step | delay |
|---|---|
| session quiet | 20 min |
| sweep (proposed: every 15 min) | 15 min |
| rollup, rules, delivery | ≤ 45 min |
| **total** | **≈ 1 h 20 min** |

## 3. What this costs

Stated before measuring, because it is the reason not to do this.

1. **A session is analysed more than once.** A session worked on for eight hours
   with 20-minute gaps could be submitted many times, and each submission is a
   full analysis on Modal. §6 predicts the multiplier; §7 rejects the amendment
   if it is worse than predicted.
2. **`received_at` changes meaning.** It becomes "when the most recent version
   arrived", not "when this session first arrived". `analyzed_at` and
   `occurred_at` are unaffected.
3. **A row now describes a session in progress.** Today every stored row is a
   finished session. After this, a row may describe a session that later grows.
   The final state is still correct because the last write wins; the
   intermediate states are new.

## 4. What is explicitly NOT changed

- **`occurred_at`** stays the trace's own start time. The time axis does not move.
- **`params_key` separation** stays. Different detector parameters remain
  different rows.
- **Alert rules** are untouched. Rule A still compares day over day within one
  baseline; rule B still reads a monthly total.
- **No detector changes.** This amendment is about when a measurement is sent
  and stored, never about what is measured.

## 5. The rejection this must survive

The original rule exists to stop double counting. The replacement must be shown
to actually stop it, not assumed to. §6 P1 is that test, and it is run against a
real session that grows, not a fixture.

## 6. Predictions (written before any of this is built)

| # | Prediction | What rejects it |
|---|---|---|
| **P1** | Submitting the same growing session 5 times leaves **exactly 1 row** in `run`, holding the **last** submission's values | 2 or more rows, or values from an earlier submission |
| **P2** | The same session submitted under two different `params_key` values leaves **2 rows** | 1 row, meaning a measurement was overwritten across parameter sets |
| **P3** | `rollup_hourly` after 5 resubmissions equals the rollup after submitting **only the final state once**, to 6 decimals | any difference, meaning aggregation still double counts |
| **P4** | On the author's machine, moving 240 → 20 min raises submissions per session-day by **no more than 6×** | above 6× |
| **P5** | Worst-case notification latency measured end to end is **under 100 minutes** | 100 minutes or more |

P1 and P3 are the ones that matter. P4 is the cost gate: if analysis volume
rises more than sixfold, the latency is being bought at a price this
pre-registration did not agree to.

## 7. What would make this amendment fail

- **P1 or P3 misses**: the replacement does not stop double counting, and the
  four hours were doing real work. The amendment is abandoned and the threshold
  stays at 240.
- **P4 misses**: the wait was also a cost control, which the original document
  did not claim and this one would have to. Reported as a limit, and the
  threshold is re-chosen from the measured multiplier rather than from 20.
- **A stored row is observed changing `occurred_at`**: the time axis moved, which
  §4 forbids. Immediate stop.

Any of these is published as a result, in the same place as the missed Corpus D
prediction.

## 8. Order of work

1. This document, merged, before anything else. (rule 8)
2. Schema migration for the uniqueness change and the upsert, with its own
   predictions in its verify block.
3. `CLOSE_AFTER` and sweep interval changed in the client.
4. Measurement against P1 through P5, published as a results document whether it
   passes or not.

Step 3 does not happen before step 2 is live. A shorter wait against the old
uniqueness rule is exactly the double counting the original document refused.
