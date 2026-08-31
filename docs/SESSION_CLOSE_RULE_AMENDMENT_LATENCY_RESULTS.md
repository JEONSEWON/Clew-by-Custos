# Session Close Rule Latency Amendment: Results

Measurement against the predictions in
[`SESSION_CLOSE_RULE_AMENDMENT_LATENCY_PREREG.md`](SESSION_CLOSE_RULE_AMENDMENT_LATENCY_PREREG.md)
§6, which its §8 step 4 requires be published "whether it passes or not".
Measured 2026-08-31, one day after the client change landed (`ec608d4`).

**Headline: P5 is rejected. Worst-case notification latency on the live
schedule is 103.48 minutes, not under 100.** The amendment itself stands: §7 lists
what would make it fail, and P5 is not on that list. What failed is the latency
figure the amendment advertised, and it failed for a reason visible in the
amendment's own arithmetic rather than in anything the change did.

A second finding, not predicted by anything: **the sweep had not been running
for two and a half hours of the measurement window, and reported no error.**

## 1. P1 through P3: the ones that mattered

Verified in Docker against the full migration chain, in tests named for the
predictions they carry (`boxdawn-cloud/migrations/test_migrations.py`). Run
2026-08-31 against the chain through `0018`: **95 collected, 95 passed.**

| # | Prediction | Test | |
|---|---|---|---|
| **P1** | a growing session leaves exactly 1 row, holding the last values | `test_p1_a_growing_session_stays_one_row_with_the_latest_values` | PASS |
| **P2** | two `params_key` values leave 2 rows | `test_p2_a_different_parameter_set_is_a_separate_row` | PASS |
| **P3** | rollup after 5 resubmissions equals the rollup after 1 final submission | `test_p3_the_rollup_matches_a_single_submission_of_the_final_state` | PASS |

P1 and P3 are the pair §5 named as the rejection the amendment had to survive:
the four hours existed to stop double counting, and the replacement had to be
shown to actually stop it. It does.

One live observation belongs next to them. Applying the new unique index found
**11 surplus rows in 7 groups, $5.45 of double-counted waste, already in the
data** from backfills predating the close rule. The index was rejected until
they were removed. The double counting the old rule was written to prevent had
happened anyway, by a route the rule did not cover.

## 2. P4: not measurable, because nothing recorded it

P4 predicted submissions per session-day would rise by no more than 6x. That
number was not anywhere:

- the ledger (`~/.clew/submitted.json`) holds **one entry per session file**,
  and each send overwrote the last, so a session sent five times looks exactly
  like a session sent once
- the run log records `done: N stored` per sweep, but not which sessions, so
  per-session counts cannot be reconstructed from it either

A prediction was written about a quantity the system does not keep. That is
reported as a gap in the pre-registration, not as a pass or a fail.

**Instrument added:** each ledger entry now carries `sends`, incremented on
every submission of that path. Entries written before the field are read as one
prior send, so the count is not short by one for the 88 sessions already on the
author's machine. `sends` counts attempts; a refused key or a rejected upload
never reached the analyser, so a cost reading takes the `ok: true` entries.

P4 is measurable from the first full day of normal operation after the fix in
§4, and is reported then. It is open, not passed.

## 3. P5: rejected on the schedule itself

P5 predicted worst-case end-to-end latency under 100 minutes. The live schedule
settles it without waiting for an observation, because an observation can only
ever be at or below the worst case:

| stage | cadence | source |
|---|---|---|
| session goes quiet | 20 min | `CLOSE_AFTER`, `src/clew/submit.py` |
| sweep | every 15 min | registered task, `src/clew/schedule.py` |
| rollup | `5 * * * *` | `migrations/0004_cron.sql` |
| rule A (waste-rate rise) | `20 * * * *` | `migrations/0010_alerts.sql` |
| rule B (cost cap) | `35 * * * *` | `migrations/0012_cost_cap.sql` |
| delivery | `50 * * * *` | `app.py`, `modal.Cron` |

Only one of the two rules reaches a person. `0013` gives rule B's events
`delivery_mode = 'email'` when the project has an address; rule A stays
`'shadow'`, frozen by the alert pre-registration's §5.1 as recorded and not
delivered, and `0010` additionally evaluates it on **completed days only**
("오늘은 평가하지 않는다"), paying up to 24 hours for a comparison that a
partial day would lock in wrong. So rule A has no notification latency to
measure, and P5 is about rule B.

Worst case from a session's last recorded event to a delivered mail, taken over
every possible position of that event within the hour:

| chain | worst case | |
|---|---|---|
| last event to stored | **34.99 min** | matches the 20 + 15 model |
| rule B, the rule that delivers | **103.48 min** | **P5 REJECTED** |
| rule A | not a notification channel | shadow, and day-gated |

The amendment's §2 table costed the tail as "rollup, rules, delivery ≤ 45 min"
and arrived at 1 h 20 m. Rule B skips the rollup entirely, and still misses,
because delivery is hourly on its own. **The 1 h 20 m figure was arithmetic on
a cadence that was never checked, in a document whose whole subject was that
cadence.**

It misses by 3.48 minutes, and re-phasing the sweep alone would clear it: over
every sweep phase the best rule B worst case is **94.98 min**, at a sweep on
the `:05` grid. That is a change made after the measurement rather than a
reading of it. P5 is judged against the schedule the amendment shipped with,
which is the one above.

Arithmetic in `field_test/diagnostics/_p5_latency_worst_case.py` and
`_p5_rule_b_cadence.py`.

## 4. The sweep was not running, and said nothing

Found while trying to observe P5 rather than compute it. One session's upload
was 136 minutes behind its last event, and the run log had a hole:

```
03:43:08Z  sweep ran
03:57 Z    power source change  (Kernel-Power 105)
04:13 ... 05:58Z   nine triggers, none of them fired, no log line, no error
05:58 Z    power source change  (Kernel-Power 105)
06:13:52Z  sweep ran, three overdue sessions at once
```

`schtasks /Create /SC MINUTE /MO 15` takes the Windows defaults, and the task it
registers carries:

```xml
<DisallowStartIfOnBatteries>true</DisallowStartIfOnBatteries>
<StopIfGoingOnBatteries>true</StopIfGoingOnBatteries>
```

with `StartWhenAvailable` absent, so false. On a laptop that means: unplugging
stops the sweep, replugging resumes it, missed triggers are never made up, and
`Get-ScheduledTaskInfo` reports `State: Ready` and `NumberOfMissedRuns: 0`
throughout. A trigger Windows declines to launch is not a failure it records
anywhere.

This is the same shape as the alert cron in the 2026-08-29 session, which ran
successfully and wrote nothing, and it was found the same way: by measuring a
number and asking why it was too large.

**Fixed** by registering the full task definition instead of the flags, with
`DisallowStartIfOnBatteries` and `StopIfGoingOnBatteries` false,
`StartWhenAvailable` true, and a bounded `ExecutionTimeLimit` so one hung sweep
cannot silence the triggers behind it. `WakeToRun` stays false: a sleeping
machine writes no sessions, so there is nothing to collect. Verified on the
live task after re-registration.

The 136-minute observation is not evidence about P5 either way. It was produced
by this defect, and P5 is rejected by §3 without it.

## 5. What would reach under 100 minutes

For rule B, which is the channel that delivers, the binding steps are its own
evaluation and the delivery job. Moving both from hourly to quarter-hourly
brings the worst case to **50.48 minutes**. Moving only one of them does almost
nothing: delivery alone reaches 95.48 minutes, and rule B alone stays at 103.48,
because whichever step is still hourly sets the floor.

**Done, later the same day**, under its own pre-registration
([`ALERT_DELIVERY_CADENCE_PREREG.md`](ALERT_DELIVERY_CADENCE_PREREG.md)) and
published in its own results
([`ALERT_DELIVERY_CADENCE_RESULTS.md`](ALERT_DELIVERY_CADENCE_RESULTS.md)).
Both halves were applied live and read back from `cron.job` and from Modal's
own log, and the measured worst case is 50.48 minutes.

**The 103.48 figure above stands as this document's result.** P5 was a
prediction about the schedule the amendment shipped with, and that schedule
missed it. A later change to a different document's schedule does not make an
earlier prediction pass, and the two numbers are not alternatives: 103.48 is
what the latency amendment achieved, 50.48 is what the cadence amendment
achieved on top of it.

## 6. What is not claimed

- **No detector change.** Nothing here touches what is measured.
- **`occurred_at` unchanged.** §4 of the prereg forbids the time axis moving,
  §7 makes it an immediate stop, and `test_a_replaced_run_keeps_the_time_axis`
  covers it.
- **P4 is open, not passed.** §2 says when it can be read.
- **P5 is rejected, and the amendment is not.** §7 names P1, P3, P4 and
  `occurred_at` as the failure conditions. A latency prediction missing means
  the latency goal was not reached, which is what §5 above is about.
