# Author-Only Delivery: Results (P1–P4)

Measurement against
[`LIVE_ALERT_AUTHOR_ONLY_DELIVERY_PREREG.md`](LIVE_ALERT_AUTHOR_ONLY_DELIVERY_PREREG.md)
§6, which its §8 step 2 requires be measured **before delivery is switched on
for anything**. Measured 2026-09-01 against a real PostgreSQL, not a mock.

**Headline: P1 through P4 pass. Nothing is switched on — the allow-list is
empty, so the chain is complete and silent. P5 and P6 need a recipient and are
measured at 60 days.**

| # | Prediction | Result |
|---|---|---|
| **P1** | one finding → one mail; a second on the same `(session, signal)` → none | **PASS** |
| **P2** | a finding for a project not on the allow-list is recorded and not sent | **PASS** |
| **P3** | server analyses caused by delivery: 0 | **PASS** |
| **P4** | ten findings in one project in one hour → 3 mails | **PASS**, exactly 3 |
| P5 | 20 live findings labelled within 60 days | not yet — needs a recipient |
| P6 | live precision within 0.20 of 0.9667 | not yet — same |

## 1. P3, and why it is a count rather than a promise

The claim is that the fast path adds no server analysis. It is asserted twice,
on both sides of the wire, because either one alone would be an argument:

- **The database function cannot receive a trace.** A test reads
  `pg_get_function_arguments('record_live_finding')` and pins the signature to
  `(uuid, text, text, jsonb)`. Nothing there can carry one.
- **The route cannot either.** `POST /live-finding` is checked for the absence
  of `UploadFile`, `File(`, `_run_analyzer` and `analyze_job` — a route that
  accepted an upload would make the signature irrelevant, because the analysis
  would start before the RPC was reached. Verified by mutation: adding
  `file: UploadFile = File(...)` to the handler fails it.

## 2. P4 and the cap that is not obvious

Ten findings in one project, one hour: **3 deliverable, 10 recorded.** The
recording and the sending are separate on purpose, so "how many were there and
how many were sent" stays answerable after the fact.

A second case sits under it and does not follow from the first. Findings
recorded **while delivery was closed** must not consume the hourly allowance
on the day it opens — otherwise the cap is already full the moment somebody is
added to the allow-list, and the first real alert never arrives. Five shadow
findings followed by four live ones still yield 3.

Both are verified by mutation: raising the cap fails two tests, ignoring the
allow-list fails two.

## 3. P1: the cap that has no expiry

One `(project, signal, session)` for ever, enforced by a partial unique index
rather than by application code. The existing `alert_event_transition_once`
does not reach these rows: `window_prev` is null on a live finding and nulls
compare unequal in a unique index, so every live row would have been distinct
from every other. That was found by writing the test, not by reading the
schema.

The second finding on a session is not an error. It returns
`{"ok": true, "recorded": false, "reason": "already_recorded"}` — something
already known rather than something that failed.

## 4. What is switched on

Nothing.

```
live_alert_allowlist rows : 0
live_repeat events        : 0
delivered                 : 0
```

`pending_live_alerts` joins the allow-list, so an empty table means the sender
has nothing to send for any project. Every project behaves exactly as it did
before this work: findings recorded locally, nothing leaving the machine.

Two independent gates hold that: the client sends nothing without `--send`, and
the server delivers nothing without a row. A client bug and a server bug would
both have to occur for a mail nobody chose.

## 5. What these four do not establish

- **Not that a mail arrives.** No mail has been sent. The Resend path is the
  one `deliver_alerts` already uses, which is evidence about that function and
  not about this one.
- **Not the precision of a live finding.** That is P6, it needs findings that
  the live path produced, and the live path has produced none — 832 watcher
  runs on 2026-09-01, 0 recorded.
- **Not that anybody answers the feedback links.** P5 is that question and it
  cannot be asked before step 3.
- **Nothing about a second project.** §8 step 5 makes widening its own
  decision and this document does not imply it.

## 6. What happens next, in order

1. One row in `live_alert_allowlist`, and one `alert_rule` with a
   `notify_email`. That is the switch, and it is a database write rather than
   a deploy — reversible by deleting the row.
2. `boxdawn watch --send` on the author's machine.
3. Wait. The measured rate is the constraint: repeats are rare, the
   restriction to idempotent tools made them rarer, and P5's 20-in-60-days is
   a prediction rather than a plan.
4. P5 and P6, published whether they pass or not.
