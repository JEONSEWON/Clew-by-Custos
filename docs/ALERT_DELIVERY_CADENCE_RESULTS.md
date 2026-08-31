# Alert Delivery Cadence: Results

Measurement against the predictions in
[`ALERT_DELIVERY_CADENCE_PREREG.md`](ALERT_DELIVERY_CADENCE_PREREG.md) §6,
which its §8 step 4 requires be published whether it passes or not. Measured
2026-08-31, the same day the pre-registration merged.

**Headline: P2, P3, P4 and P5 pass. P1 is open, because it is the one that
cannot be measured before a person applies the migration.**

| # | Prediction | Result |
|---|---|---|
| **P1** | worst case 50.48 min over the crons **as applied** | **open**: needs the live apply |
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

## 4. P1 is open, and stays open until a person applies it

P1 is arithmetic on the crons **as they appear in `cron.job`**, deliberately
not on the crons as written in the migration. The reason is the failure mode
this area keeps producing: a cron that did not take. The migration's own verify
block carries the predictions for that moment, including one that matters more
than the schedule string:

> `evaluate-cost-cap` appearing **twice** means the named `cron.schedule` added
> a job instead of updating one, the old `35` entry is still live, and rule B
> runs five times an hour.

Applying migrations to live is a person's job (`migrations/README.md`: no
service session here holds credentials for the live database), and the Modal
deploy is its pair. Neither is done in this session.

**Until both are applied, the published worst-case latency is still 103.48
minutes**, the figure in
[`SESSION_CLOSE_RULE_AMENDMENT_LATENCY_RESULTS.md`](SESSION_CLOSE_RULE_AMENDMENT_LATENCY_RESULTS.md)
§3. Half of this change would make it 95.48 or leave it at 103.48; neither is
50.48, and publishing 50.48 before both halves are live would be publishing a
number that is not true.

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
- **50.48 minutes is not a published figure yet.** See §4.
- **50.48 minutes is not "real-time".** Whatever this reduces, it does not turn
  the alert channel into monitoring, and the web session's surfaces keep
  alerting in `building` rather than `shipped` on that basis.
