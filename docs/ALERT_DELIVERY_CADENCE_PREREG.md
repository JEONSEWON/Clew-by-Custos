# Alert Delivery Cadence (Pre-registration)

**Status.** Amendment to the tail of the chain that
[`SESSION_CLOSE_RULE_AMENDMENT_LATENCY_PREREG.md`](SESSION_CLOSE_RULE_AMENDMENT_LATENCY_PREREG.md)
shortened the head of. Per `feedback_rule_8` this document is pushed and
PR-opened **before any cron, schema, or code change lands**. The change in §2,
the predictions in §6 and the rejection conditions in §7 are frozen positions.
Adjusting them after seeing results is not allowed.

---

## 0. What is wrong

[`SESSION_CLOSE_RULE_AMENDMENT_LATENCY_RESULTS.md`](SESSION_CLOSE_RULE_AMENDMENT_LATENCY_RESULTS.md)
§3 measured the chain that reaches a person and found **103.48 minutes** worst
case, against a prediction of under 100. The head of the chain was shortened
from four hours to twenty minutes and the tail was left hourly, so the tail is
now almost all of it.

This is not a rounding problem. `project_mast_coverage_plan` puts latency first
and verification-failure detection second, for a stated reason: a failed task
ends inside its session, and a notice an hour and three quarters later is about
something nobody can act on any more. Step 1 is not closed, and step 2 is the
next thing to be built on top of it.

## 1. Why the tail is hourly

None of the four phases were chosen against a latency budget. They were chosen
so the jobs would not collide:

| job | cron | why that phase |
|---|---|---|
| `rollup-hourly` | `5 * * * *` | `0004`: hourly because rule A compares one day against the previous one |
| `evaluate-alerts` (rule A) | `20 * * * *` | `0010`: after the rollup it reads |
| `evaluate-cost-cap` (rule B) | `35 * * * *` | `0012`, in its own words: "롤업(:05) · 규칙 A(:20) 와 겹치지 않게 :35 에 둔다" |
| `deliver_alerts` | `50 * * * *` | `app.py`: after both rules |

Fifteen minutes apart, which is a pipeline that completes once per hour. That
was the right shape when the head of the chain was four hours: an hour of tail
against four hours of head is noise. Against twenty minutes of head it is the
whole figure.

## 2. The change

**Rule B and delivery run four times an hour. Nothing else moves.**

```
evaluate-cost-cap    35 * * * *        ->  8,23,38,53 * * * *
deliver_alerts       50 * * * *        ->  12,27,42,57 * * * *
```

Phases keep the no-collision property of §1: rule B still runs after the rollup
(`:05` grid) and rule A (`:20` grid) in each quarter hour, and delivery still
runs after rule B.

Rule B is the only rule this can help. `0013` gives its events
`delivery_mode = 'email'` when the project has an address; rule A's stay
`'shadow'`, frozen by the alert pre-registration §5.1 as recorded and not
delivered. Rule B also skips the rollup: it joins `run` directly and counts the
period in progress, so it can fire on a session stored minutes ago.

Rule A is left alone on purpose, and not only because it does not deliver.
`0010` evaluates it on **completed days only**, with the reason written down: a
day in progress changes value as it fills, and evaluating it hourly would let
the unique index lock the day's first value as the transition and never record
the finished day. Evaluating rule A more often would make it wrong, not faster.

## 3. What this costs

Stated before measuring, because it is the reason not to do this.

1. **Four times the rule B evaluations.** `evaluate_cost_cap` scans `run` for
   each project with a limit, over the day and month windows. At current sizes
   (`run` = 72 rows) that is small, and it does not stay small.
2. **Four times the delivery invocations.** `deliver_alerts` is a Modal cron, so
   this is 2,880 container starts a month instead of 720, most of them finding
   nothing to send.
3. **Four times the rows in `cron.job_run_details`.** The nightly prune does not
   cover pg_cron's own history.

## 4. What is explicitly NOT changed

- **`CLOSE_AFTER` = 20 min and the 15-minute sweep.** The head of the chain
  stays as the latency amendment left it.
- **The sweep phase.** Re-phasing the client sweep onto the `:05` grid would by
  itself bring rule B to 94.98 minutes, inside the old prediction. It is not
  done here: the sweep is registered on each user's machine by a released
  client, so a latency claim resting on its phase would be true on different
  machines at different times. The tail is ours and moves for everyone at once.
- **`rollup-hourly` and rule A.** For the reasons in §2.
- **Both unique indexes.** `alert_event_cost_cap_once` and
  `alert_event_transition_once` are what make one alert per period, and they are
  what §5 tests rather than assumes.
- **Thresholds and detection.** Nothing here changes what is measured, what
  counts as waste, or when a rule fires. Only how soon it is noticed.
- **`occurred_at`.** The time axis does not move.

## 5. The rejection this must survive

Evaluating a rule four times as often must not tell anyone four times.

The guard already exists: `alert_event_cost_cap_once` is unique on
`(project_id, signal, (payload->>'period_kind'), window_curr)` and the insert
ends `on conflict do nothing`, so one project's daily cap produces one row per
day no matter how often the rule runs. Delivery has its own: `deliver_alerts`
only takes rows with `delivered_at is null`, and `mark_alert_delivered` stamps
them.

Both are load-bearing, both were written under an hourly cadence, and neither
has been exercised at four times that rate. §6 P2 and P5 test them against a
sequence of evaluations inside one period, not against a fixture.

## 6. Predictions (written before any of this is built)

| # | Prediction | What rejects it |
|---|---|---|
| **P1** | worst-case last event to delivered mail, over the applied crons, is **50.48 min** | any other figure from the same arithmetic on the crons actually in `cron.job` |
| **P2** | rule B evaluated 4 times inside one day, past its limit, leaves **exactly 1** `alert_event` row for that `period_kind` | 2 or more rows |
| **P3** | crossing the limit at 09:10 fires on the **09:23** evaluation, not on the next hour's | an event whose `evaluated_through` is more than 15 min past the crossing |
| **P4** | one `evaluate_cost_cap` call stays under **100 ms** at current table sizes | 100 ms or more |
| **P5** | 4 delivery runs against 1 undelivered event send **exactly 1** mail | 2 or more sends, or 0 |

P2 and P5 are the ones that matter. P1 is arithmetic and is checked against the
crons as applied, not as written here, because a cron that did not take is the
failure mode this whole area keeps producing.

## 7. What would make this amendment fail

- **P2 or P5 misses**: the guards did not hold at four times the rate, and the
  cadence goes back to hourly. A duplicate alert is worse than a late one: it
  teaches the reader to ignore the channel.
- **P4 misses**: the latency is being bought with database time this
  pre-registration did not agree to. Reported as a limit, and the cadence is
  re-chosen from the measured cost rather than from four times an hour.
- **An `alert_event` row is observed changing `window_curr`**: the period a
  notice is about must not move under it. Immediate stop.

Any of these is published as a result, in the same place as the missed Corpus D
prediction and the rejected P5.

## 8. Order of work

1. This document, merged, before anything else. (rule 8)
2. A migration that reschedules `evaluate-cost-cap`, with its own predictions in
   its verify block, plus the Modal cron change for `deliver_alerts`. The two
   land together: delivery alone reaches 95.48 minutes and rule B alone stays at
   103.48, so either one shipped without the other buys nothing and publishes a
   figure that is not true.
3. Docker tests for P2, P3, P5 against the migration chain.
4. Measurement against P1 through P5, published as a results document whether it
   passes or not.

Step 2 does not happen before step 3 is written. The guards in §5 were written
for an hourly cadence, and finding out in production that they do not hold four
times an hour means someone got four emails.
