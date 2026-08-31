# Session Close Rule Latency Amendment: Results

Measurement against the predictions in
[`SESSION_CLOSE_RULE_AMENDMENT_LATENCY_PREREG.md`](SESSION_CLOSE_RULE_AMENDMENT_LATENCY_PREREG.md)
§6, which its §8 step 4 requires be published "whether it passes or not".
Measured 2026-08-31, one day after the client change landed (`ec608d4`).

**Headline: P5 is rejected. Worst-case notification latency on the live
schedule is 133 minutes, not under 100.** The amendment itself stands: §7 lists
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

Worst case from a session's last recorded event to a delivered mail, taken over
every possible position of that event within the hour:

| chain | worst case | |
|---|---|---|
| last event to stored | **35.00 min** | matches the 20 + 15 model |
| rule B (no rollup: it joins `run` directly) | **103.47 min** | MISS |
| rule A (waits for the rollup) | **133.47 min** | **P5 REJECTED** |

The amendment's §2 table costed the tail as "rollup, rules, delivery ≤ 45 min"
and arrived at 1 h 20 m. The rollup alone is hourly, so the tail is at least
about an hour on its own. **The 1 h 20 m figure was arithmetic on a cadence
that was never checked, in a document whose whole subject was that cadence.**

Re-phasing the sweep cannot rescue it. Over every possible sweep phase the best
achievable worst case is **124.99 min** for rule A and **94.99 min** for rule
B: shortening the head of a chain whose tail is hourly moves the total by
minutes.

Arithmetic in `field_test/diagnostics/_p5_latency_worst_case.py`.

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

With the same client, moving the four tail jobs from hourly to quarter-hourly
brings the worst case to **43.48 minutes** for both rules.

That is not done here. It changes the latency this product claims, so it takes
its own pre-registration with its own predictions, including what four times
the rule-evaluation frequency costs on the database. Until then the honest
figure is the one in §3, and any published latency number is that one.

## 6. What is not claimed

- **No detector change.** Nothing here touches what is measured.
- **`occurred_at` unchanged.** §4 of the prereg forbids the time axis moving,
  §7 makes it an immediate stop, and `test_a_replaced_run_keeps_the_time_axis`
  covers it.
- **P4 is open, not passed.** §2 says when it can be read.
- **P5 is rejected, and the amendment is not.** §7 names P1, P3, P4 and
  `occurred_at` as the failure conditions. A latency prediction missing means
  the latency goal was not reached, which is what §5 above is about.
