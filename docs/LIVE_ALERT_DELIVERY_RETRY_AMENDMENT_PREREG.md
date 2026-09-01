# Live Alert Delivery: Retry, and the Key That Names the Project (Amendment)

Amends `LIVE_ALERT_AUTHOR_ONLY_DELIVERY_PREREG.md`. Written 2026-09-01, before
the switch in its §8 step 3 is thrown.

That document's §8 says findings accumulate once delivery is on. Two things
found by reading the shipped code say they would not accumulate at all, and
both are on the path between "a finding was recorded" and "a person was told".

---

## 0. What is wrong

### 0.1 One attempt, then silence

`on_finding` is called once, at the moment a finding is first recorded
(`src/clew/live.py:293`). If that send fails the finding is never offered
again. The field built to track it is dead:

```python
delivered: bool = False    # src/clew/live.py:79
```

Nothing in `src/clew` reads or writes it. The log keeps `recorded=1 sent=0`, so
the loss is visible afterwards and not recoverable.

P5 asks for **20 labelled findings in 60 days**. Findings arrive at roughly one
per three days. **One lost send is 5 per cent of the sample**, and the sample
is what P6 is computed on.

### 0.2 Nothing can be delivered at all today — measured, not inferred

`live_send.send_finding` takes no key from its caller, so it falls back to
`read_key()`, which reads `~/.clew/credentials.yaml`. The watcher's targets
drop the per-project key on the way in:

```python
targets = [(t.project, t.root) for t in load_targets()]   # __main__.py:540
```

`load_targets()` returns `Target(project, root, api_key)` and the third field is
discarded. Run on the author's machine, 2026-09-01:

```
CREDENTIALS_PATH  C:\Users\User\.clew\credentials.yaml   exists False
read_key()        -> None
send_finding      -> SendResult(attempted=False, ok=False, reason='no_key')
```

So with the allow-list switched on and `--send` registered, **every finding
would fail with `no_key`.** Retrying that forever is not a fix.

And when a global key does exist, it is worse than nothing here: the server
binds a finding to a project **through the key** (`resolve_api_key`), not
through the finding's `project` field. Three projects in `projects.yaml`
sending under one key would record all three under whichever project that key
names — the same blending `load_targets` exists to prevent, arrived at through
a different door.

---

## 1. What changes

**One delivery path, tried until it lands.**

1. `on_finding` stops sending. A finding is recorded with `delivered=False`.
2. After the sweep, a **drain** step loads the ledger, offers every
   `delivered=False` finding to the server, flips the ones that land, and saves.
3. First attempt and retry are the same call. There is no separate first-try
   branch that could behave differently from the retry.
4. The retry interval is **the schedule that already exists** — the watcher runs
   every minute (`clew watch --once --auto`). No timer, no daemon, no new task.
5. Each finding is sent **under its own project's key**, resolved by matching the
   finding's `project` against `load_targets()`. A finding whose project has no
   key is not sent, and says so.

The drain lives in the CLI, not in `live.py`. `live.py` must not import
`live_send` — a test parses its imports and that separation is the shipped form
of the shadow guarantee. Retry does not get to weaken it.

## 2. What is NOT changed

- **The trigger.** Idempotent-only, first confirmed pair, one per
  `(session, signal)`, three per project per hour. Untouched.
- **The detection.** φ, N, `confirm_pair`, the earliest-pair rule.
- **The payload.** Still a session key, a tool name and two counts. A retry
  sends the same bytes as the first attempt.
- **The allow-list and shadow mode.** The server still decides delivery. A
  client that retries harder does not become allowed.
- **`latency_seconds`.** Stamped into the finding when the scan finished. A
  retry three hours later reports the same number, because it is a property of
  the repeat and not of the delivery.
- **Every stored figure, every waste rate, every published number.**

## 3. What counts as delivered

`ok == true`, which includes `reason == "already_recorded"`.

The server's `record_live_finding` inserts `on conflict do nothing` and answers
a duplicate with `{"ok": true, "recorded": false, "reason":
"already_recorded"}` (`migrations/0021_live_alert_delivery.sql:143`). That is
the answer to the case retry exists for: the server committed and the response
was lost. Treating it as failure would retry a known finding for ever; treating
it as delivery is what it is.

Anything else — `no_key`, `http_401`, a transport error, `ok == false` — leaves
`delivered=False` and the finding is offered again next minute.

**No give-up counter.** A finding that can never be delivered is attempted once
a minute for ever, and that is deliberate: the alternative is a finding that
goes quiet twice. Instead every run's log line carries `pending=N` and, when N
is not zero, the last reason. A permanent failure is then loud once a minute
rather than silent for ever. This costs one small HTTPS request per minute in a
state that is itself a bug.

## 4. What this does to the original predictions

- **P1 (one mail per finding) holds, and retry is why it needs saying.** The
  unique index plus `on conflict do nothing` means a second POST for the same
  `(project, session_key, signal)` writes no row and sends no mail. Retry
  cannot produce a second mail; if it could, this amendment would be rejected
  by its own R3 below.
- **P4 (three per project per hour) holds.** The cap is counted at insert time
  over `delivery_mode = 'email'`. A finding recorded as `shadow` because the cap
  was full stays shadow — a retry gets `already_recorded` and does not
  re-evaluate it. Retry does not resurrect suppressed findings.
- **A retried finding can land in a later hour than it happened.** If the first
  attempt never reached the server, the row is created when a later attempt
  succeeds, and the cap it is measured against is that later hour's. The mail is
  then late, and `latency_seconds` in its body still describes the repeat, not
  the mail. §5 of the original document is where lateness gets reported.
- **P5 is the reason for this document.** It does not change P5; it removes one
  way of losing it.

## 5. Predictions

| # | Prediction | What rejects it |
|---|---|---|
| **R1** | a finding whose send fails is offered again on the next sweep, with `delivered` still false in the ledger | one attempt only |
| **R2** | a finding answered `already_recorded` is marked delivered and never offered again | a second attempt |
| **R3** | two POSTs for the same `(session, signal)` produce **one** mail | two, which rejects retry entirely |
| **R4** | with delivery off, the drain attempts nothing and every finding stays `delivered=False` | any attempt, which would break the shadow guarantee |
| **R5** | each finding is sent under the key of **its own** project; a finding whose project has no key is not sent | a send under another project's key |
| **R6** | the run's log line carries `pending=N`, non-zero exactly when some finding is undelivered | a silent run |
| **R7** | `live.py` still does not import `live_send` | any import |

R3 and R4 are the two that would make retry unsafe rather than merely
incomplete. R5 is §0.2, which is why it is a prediction and not a footnote.

## 5.1 Dry-run before approval, and what it found instead

R3's mechanism was checked against the deployed endpoint before this document
was submitted, because a rule that rests on a server behaviour should be
checked against the server. Three POSTs of the same `session_key`, with the
allow-list empty so nothing could be mailed:

```
POST /live-finding  (valid key, same session_key, x3)  ->  502 {"ok":false,"reason":"ingest_error"}
POST /live-finding  (no key)                           ->  401 {"ok":false,"reason":"no_key"}
POST /live-finding  (unknown key)                      ->  401 {"ok":false,"reason":"bad_key"}
```

Modal log: `live_finding rpc failed kind=HTTPStatusError`, three times.

**R3 could not be measured, because `record_live_finding` was not callable on
the live database.** The grant fix was merged (`cloud 7629714`) and had never
been executed — the Supabase dashboard was down on 2026-08-31 and it is the
only SQL path this machine has. The key resolution around it was correct, which
is how we knew this was the RPC and not the credential.

### The same run, after the grants were executed (2026-09-01, later)

```
POST /live-finding  (valid key, new session_key)  ->  200 {"ok":true,"event_id":487,"recorded":true,"delivery_mode":"shadow"}
POST /live-finding  (same session_key, 2nd)       ->  200 {"ok":true,"recorded":false,"reason":"already_recorded"}
POST /live-finding  (same session_key, 3rd)       ->  200 {"ok":true,"recorded":false,"reason":"already_recorded"}
```

**§3's flip condition is now measured rather than read off the SQL.** A repeat
POST is `ok: true` with `recorded: false` and `already_recorded`, which is
exactly the answer the drain must treat as delivered.

`delivery_mode: "shadow"` on the first POST also re-confirms the original P2
against the live server: the allow-list is empty, so nothing could be mailed,
and this dry-run therefore cost no mail. Row `alert_event 487` carries
`params_key = 'probe-retry-dryrun-20260901-0001'` and is a probe: it must be
excluded from any finding or label count.

R3 itself — *two POSTs, one mail* — still needs email mode to count mails, so it
remains a prediction until the allow-list row exists. What is settled is that
the second POST writes no row.

The feedback links are alive too, checked without writing a label (a
non-existent event id distinguishes "the function ran and found nothing" from
"the function cannot be called"):

```
GET /live-feedback/999999999?real=yes    ->  404 <p>Unknown alert.</p>      (was 502)
GET /live-feedback/999999999?real=maybe  ->  400 <p>Unknown answer.</p>
```

`pending_live_alerts` is the one of the four that no request of ours calls — the
scheduled sender does — and it was answering `403 42501 permission denied for
function pending_live_alerts` on every run up to 22:06 KST. Those runs all
predate the grants. Asked directly instead of inferred from a log:

```sql
select p.oid::regprocedure, has_function_privilege('service_role', p.oid, 'EXECUTE') ...
```

```
record_live_finding(uuid,text,text,jsonb)   true
pending_live_alerts(integer)                true
mark_live_delivered(bigint)                 true
record_live_feedback(bigint,boolean)        true
```

Four rows, all true, **and four signatures** — no overload, which is the failure
this query was written to rule out. 0021's own verify block counts
`has_function_privilege` by `proname`, so it would answer 4 even if a second
overload of one name were the one being called; a signature-level read cannot.

Confirming the sender itself goes quiet is a log line on the next scheduled run
and belongs in step 2 of §7.

## 6. What would make this fail

- **R3 misses**: stop. Retry becomes a mailing list and the caps were what made
  one recipient safe.
- **R4 misses**: stop and revert. Shadow is the promise every project not on the
  allow-list is running under.
- **R5 misses**: stop before switching on. A finding recorded under the wrong
  project is a wrong row in the baseline rule A is opened against, and it does
  not announce itself.
- **R1, R2, R6 miss**: the retry is incomplete, not unsafe. Fix and re-measure
  before the switch.

## 7. Order of work

1. This document, merged, before any code.
2. The drain, the per-project key, and the log line, with tests. R1–R7 measured
   on this machine before the allow-list row is inserted.
3. Then, and only then, `live_alert_allowlist` + `alert_rule` + re-registering
   the task with `--send`.
4. P5 and P6 at 60 days, per the original §8.

★ Step 3 was going to happen before any of this. On the measurement in §0.2 it
would have produced sixty days of `no_key` and a results document reporting
that live findings cannot be validated on one machine — a conclusion that would
have been about a missing file.
