# Alert Delivery Cadence: Results

Measurement against the predictions in
[`ALERT_DELIVERY_CADENCE_PREREG.md`](ALERT_DELIVERY_CADENCE_PREREG.md) §6,
which its §8 step 4 requires be published whether it passes or not. Measured
2026-08-31, the same day the pre-registration merged.

**Headline: all five pass. Applied live 2026-08-31; worst-case notification
latency went from 103.48 minutes to 50.48.**

| # | Prediction | Result |
|---|---|---|
| **P1** | worst case 50.48 min over the crons **as applied** | **PASS**, 50.48 |
| **P2** | 4 evaluations inside one day leave exactly 1 `alert_event` | **PASS** |
| **P3** | a 09:10 crossing fires on the 09:23 evaluation | **PASS** |
| **P4** | one `evaluate_cost_cap` under 100 ms | **PASS**, 9.13 / 9.92 / 11.59 ms |
| **P5** | 4 delivery runs against 1 event send exactly 1 | **PASS** |

## 1. The two guards §5 said to test rather than assume

Both were written under an hourly cadence and neither had been exercised
faster. Both hold.

**P2, the dedup key.** Four evaluations at four distinct instants inside one
day, past the limit, leave one row. The distinction this draws is not
academic: an existing test already ran the evaluator four times, but at the
*same* `p_now`, so it could not tell a period-scoped key from an
instant-scoped one. Under the old cadence that gap was worth 24 mails a day;
under this one it is 96. Mutating `alert_event_cost_cap_once` to key on
`payload->>'evaluated_through'` instead of `window_curr` fails the test.

**P5, the delivery filter.** Four delivery passes hand one alert over once.
`mark_alert_delivered` had **no test at all** before this, and
`delivered_at is null` inside `pending_alerts` is the only thing between a
quarter-hourly delivery job and four copies of one mail. Removing that line
fails the test.

## 2. P3: the change does what it is for

A crossing at 09:10 produces the alert on the 09:23 evaluation, with
`evaluated_through` inside the 15-minute bound §6 named. Under the hourly
cadence the same crossing waited for 10:35.

Mutating the live `evaluate_cost_cap` to exclude the period in progress fails
this. Note that the live definition is `0013`'s, not `0012`'s: `0013` rewrote
the function to derive `delivery_mode` from whether a recipient exists.
Mutating `0012`'s copy proves nothing about behaviour, which is worth writing
down because it is not visible from the filename.

## 3. P4: the cost of evaluating four times as often

`evaluate_cost_cap` over ten calls, against a 20-row `run` table in Docker:

| min | median | max |
|---|---|---|
| 9.13 ms | 9.92 ms | 11.59 ms |

Against a predicted bound of 100 ms. Four calls an hour instead of one adds
about 30 ms of database time per hour at this size, which is the cost §3 of the
pre-registration said to state before agreeing to it.

Measured rather than asserted in the suite. A timing assertion on a Docker
container inside CI is flaky by construction, and a flaky guard gets skipped,
which is worse than no guard. The number is here instead.

**This does not stay true as the table grows.** The query scans `run` for the
period per project with a limit; 20 rows is not 20,000. It is a reading at
today's size, not a bound.

## 4. P1: measured on the crons as applied

Applied live 2026-08-31. P1 was written against the crons **as they appear in
`cron.job`**, deliberately not as written in the migration, because a cron that
did not take is the failure this area keeps producing. Both halves were read
back rather than assumed.

**Rule B**, from the migration's own verify block against the live database:

```
evaluate-alerts     '20 * * * *'            active   unchanged
evaluate-cost-cap   '8,23,38,53 * * * *'    active   <- this change
prune-details       '30 3 * * *'            active   unchanged
rollup-hourly       '5 * * * *'             active   unchanged
```

Four jobs, and `evaluate-cost-cap` on **one** row. That was the stop condition
the migration named: a second row would have meant the named `cron.schedule`
added a job instead of updating one, the old `35` entry still live, and rule B
running five times an hour. It updated.

**Delivery**, from Modal's own log, which writes one line per run:

```
19:50:07 KST   deliver_alerts ran pending=1 sent=1 failed=0    hourly
20:50:05 KST   deliver_alerts ran pending=0 sent=0 failed=0    hourly, last before deploy
20:57:05 KST   deliver_alerts ran pending=0 sent=0 failed=0    <- the new schedule
```

The `:57` run is the evidence. Under the previous schedule the next run after
20:50 would have been 21:50.

**Worst case over those two, plus the 20-minute close rule and the 15-minute
sweep: 50.48 minutes.** P1 predicted 50.48.

| | worst case |
|---|---|
| before | 103.48 min |
| **after** | **50.48 min** |
| had only rule B moved | 103.48 min |
| had only delivery moved | 95.48 min |

The last two rows are why both landed in one commit. Either alone buys nothing
or almost nothing, because whichever step is still hourly sets the floor, and
shipping half of it would have published a figure that is not true.

Arithmetic in `field_test/diagnostics/_p5_rule_b_cadence.py`, run against the
schedules quoted above rather than the ones in the source.

## 5. Two guards that were not guards

Neither of these is in §6. Both were found by the work failing rather than by
review, and both are the same shape as the finding that opened the previous
results document: a check that passes while the thing it checks is broken.

**The cron strip ran off a list of filenames.** `conftest` stripped `pg_cron`
statements from `("0010_alerts.sql", "0012_cost_cap.sql")`. `0019` schedules
something and was not on the list, so the chain failed with
`schema "cron" does not exist`, reported as 97 setup errors naming the first
test rather than the file. The list was two long and this change made it three,
which is the point at which the list is the defect. It now asks the file.

**The strip's own assert only checked that `cron.` was gone.** A key name
quoted inside a comment let one pattern start matching in prose and run through
the statement that followed it, swallowing a whole `select` and leaving the
wreckage behind a `--`. `cron.` was gone, so the assert passed, and the SQL was
invalid.

The first replacement for that assert **also did not work**: counting
parentheses. The wreckage ends up inside a comment, so comment-stripped text is
balanced and simply missing a statement, and the count agrees. What works is
counting statement terminators, one per `cron.schedule` removed. Written down
because the fix for a check that does not bite was itself a check that did not
bite, inside the commit that was fixing that class.

**And one of this document's own tests survived its first mutation.** The test
asserting the new schedule read the migration as text, and the migration quotes
the new cadence in its prediction block, so setting the executable schedule
back to `'35 * * * *'` left the test passing. It reads executable SQL now.

## 6. What is not claimed

- **No detector change, no threshold change.** What fires and when is
  identical; only how soon anyone is told changes.
- **Rule A is untouched**, and not because it is shadow. `0010` evaluates it on
  completed days only for a written reason: a day in progress changes value as
  it fills, and evaluating it more often would let the unique index lock the
  day's first value as the transition. Evaluating rule A sooner makes it wrong,
  not faster.
- **`occurred_at` unchanged.**
- **50.48 minutes applies to the cost-cap channel only.** Rule A does not
  deliver and is day-gated, so it has no notification latency to shorten.
- **50.48 minutes is not "real-time".** Whatever this reduces, it does not turn
  the alert channel into monitoring, and the web session's surfaces keep
  alerting in `building` rather than `shipped` on that basis.
