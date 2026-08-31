# Live Failure Alert (Pre-registration)

**Status.** New alert path. Per `feedback_rule_8` this document is pushed and
PR-opened **before any code lands**. The design in §2, the thresholds in §3, the
predictions in §6 and the rejection conditions in §7 are frozen positions.
Adjusting them after seeing results is not allowed.

---

## 0. What is wrong

Two things, and they are the same thing seen twice.

**The alert watches the symptom's total.** The only alert that reaches a person
sums `analyzed_cost` over a period and fires when it crosses an absolute limit
(`0013_alert_delivery.sql:88,116`). Not waste, not a rise, not a failure: total
spend. A project that burns 90% of its tokens on repeated work and stays under
the cap is never told. `feedback_failure_and_cost_are_one` has said for two
weeks that waste is the *symptom* of failure and the two must be connected
rather than listed, and the alert we built connects neither.

**And it arrives too late to act on.** Measured worst case 50.48 minutes, median
43.0 ([`ALERT_DELIVERY_CADENCE_RESULTS.md`](ALERT_DELIVERY_CADENCE_RESULTS.md)).
For a leak that repeats, late is fine: catching it after run 1 saves runs 2
through 1000. For a failure it is not. The user's words, and they are the
sharper version of what the latency amendment already said: *"오류가 터지고
43분에 알람이 온다? 아무 소용이 없음."*

## 1. Why the 43 minutes cannot be cut on the current path

The chain is 20 minutes of waiting for the session to go quiet, then up to 15
for the sweep, then the server crons. The crons were tightened once already.
**The 20 minutes is the floor and it is structural**: we upload finished
sessions, because a live session uploaded every sweep is analysed every sweep.

That cost is not hypothetical. A 546-span trace takes 266 seconds and 4.6 GB
peak (`reference_analyzer_cost_not_bytes`). A three-hour session swept every two
minutes is 90 analyses of a growing file. Cutting the wait on this path buys
latency with an unbounded server bill.

So the fast path cannot be the server path.

## 2. The design: detect locally, measure centrally

**Two paths, different jobs, and no number crosses between them.**

```
fast (local)    the client watches the live session file
                -> a signal appears -> it asks the server to send one mail
                no upload, no analysis, no stored row

slow (server)   unchanged. session closes -> upload -> analyse -> store
                -> roll up -> cost cap -> mail.  43 minutes, and that is fine
                for a cap
```

The detection engine already runs on the user's machine: the CLI *is* the
analyser. The 20-minute wait exists for storage comparability, not for
detection.

**What crosses the wire is a finding, not a trace.** A small POST naming the
signal, the session, and the counts. That is deliberate: it keeps the fast path
free of analysis cost, and it keeps traces off the server on a path nobody has
measured yet. It also means the server is emailing something the client
asserted, which §3 bounds.

## 3. The signal, and the thresholds

### 3.1 Which failure mode

**FM-1.3, step repetition.** Not FM-3.2, which we have just measured a judge on.

Three reasons, in order:

1. **It is both the failure and the cost.** Repetition is the mode whose symptom
   is the token burn, which is the connection this document exists to make.
2. **It is the one axis measured on four corpora**, and the only one that
   reaches a person's situation deterministically today.
3. **It is detectable while the session runs.** Structural candidates are
   sha256 and normalised-input matching, and confirmation is
   `is_semantic_duplicate(origin, candidate, embedder, phi)` — **two embeddings
   per pair**, with a sqlite cache already behind it. The whole-trace cost does
   not apply: a live watcher confirms one pair at a time.

FM-3.2 is a **session-end** finding. "You changed code and never checked it" is
not something to interrupt anyone with mid-session, and it stays on the slow
path.

### 3.2 When it fires

Measured on 86 real sessions (`field_test/diagnostics/_live_alert_frequency.py`):

| | |
|---|---|
| sessions with any structural repeat candidate | **32 of 86 (37%)** |
| candidates per such session | min 1, **median 2**, mean 4.1, max 24 |
| tool call at which the first candidate appears | **median 98**, min 9, max 463 |

**One alert per session, on the first confirmed pair. Frozen.**

Median 2 candidates per session and a maximum of 24 is why. Alerting per
candidate means two mails from a typical session and twenty-four from the worst,
and an alert channel that sends twenty-four is a channel people filter. The
first confirmed repeat is the moment the session's shape is known; the rest is
detail for the report.

- **Trigger:** the first structurally-matched pair whose φ confirmation passes.
- **Cap:** one live alert per `(session, signal)`, ever. The ledger records it.
- **Also capped:** at most 3 live alerts per project per hour, across sessions.
  A machine running ten agents at once must not send ten mails.
- **Not fired** when the session already ended: that is the slow path's job.

### 3.3 Shadow first, and what opens it

**The path ships in shadow: recorded locally, nothing sent.** Same discipline
rule A has carried since `0010`, and for the same reason — a false alarm that
interrupts someone mid-session costs more than a late one, and we have no
false-positive rate for a live trigger.

Delivery opens only when §6 P3 is met on hand-labelled live findings. That is a
separate decision, published as a result.

## 4. What is explicitly NOT changed

- **The slow path.** `CLOSE_AFTER`, the sweep, the rollup, both rules and the
  delivery cron stay exactly as they are. The 43 minutes remains the published
  figure for the cost cap.
- **The cost cap alert.** It keeps summing `analyzed_cost`. This document adds a
  channel; it does not repair that one.
- **Rule A.** Still shadow, still frozen, still day-gated.
- **Every stored number.** No `run` row, no rollup, no `waste_span_count`, no
  waste rate, no cost figure is written or read differently.
  `wasteful == (waste_span_count > 0)` stays an identity.
- **φ, N, the embedding model, and the detector thresholds.** The live path
  calls the same confirmation with the same φ. A pair that the batch path would
  call a duplicate is the same pair here.
- **The §29.2 tool-error gate.**
- **`preprocess_trace` is still not run on Claude Code traces.**

## 5. The rejection this must survive

**A live alert must be right, and it must not cost anything on the server.**

Precision first. The precedents are all kills: re-read at 0.000–0.033, args-only
at 0.633 against a pre-registered 0.70, `unverified_edit` at 0.3250. A live
alert is worse than those when wrong, because it interrupts. **The gate is 0.70
on hand labels**, the same number for the same reason, and shadow mode is what
makes measuring it possible without anyone being interrupted while we find out.

Cost second, and it is a *count*, not a feeling: the fast path must add **zero**
server analyses. If a live alert causes an upload or an analysis, the design has
failed regardless of its precision, because that is the constraint §1 says makes
the whole split necessary.

Third, and named because it is the new risk this path introduces: **the server
will email what a client asserts.** The endpoint takes a finding, not a trace,
so nothing validates it. It is bounded by the key (a project's own address), by
§3.2's caps, and by the finding being one enum value with counts rather than
free text. §6 P5 tests that the caps hold.

## 6. Predictions (written before any code)

| # | Prediction | What rejects it |
|---|---|---|
| **P1** | on the 86 local sessions, shadow mode records **32** findings, one per session with a candidate | any other count: the live path and the batch detector disagree about the same pairs |
| **P2** | median time from the confirmed pair's second span to the recorded finding is **under 3 minutes** | 3 minutes or more |
| **P3** | precision ≥ **0.70** on 30 hand-labelled shadow findings | below 0.70 |
| **P4** | server analyses caused by the fast path: **0** | any |
| **P5** | a session that produces 24 candidates records **1** finding; a project with 10 concurrent sessions records at most **3** in an hour | any excess |

P3 is the gate for opening delivery. P4 is the gate for the design. P1 is the
one that must pass before labelling anything, for the reason the last
pre-registration found out: labelling the output of a rule that does not match
its own detector measures nothing.

**Written expectation, not a prediction:** P2 is at risk from the watcher's poll
interval, not from the detection. Confirmation is two cached embeddings.

## 7. What would make this fail

- **P4 misses**: stop. The split in §2 exists to keep server cost flat, and a
  fast path that uploads is the slow path with extra steps.
- **P3 misses**: the finding stays in shadow permanently and is reported as a
  measured false-positive rate. It does not ship as a mail at a lower gate.
- **P1 misses**: stop before labelling. The live path and the batch detector
  must agree on the same trace before either is trusted about a new one.
- **P5 misses**: the caps are the difference between an alert and a mailing
  list. Fix and re-measure before anything opens.
- **A stored figure moves**: immediate stop. §4 draws that line.

Any of these is published as a result, in the same place as the missed Corpus D
prediction, the rejected latency P5, and the `unverified_edit` kill.

## 8. Order of work

1. This document, merged, before any code. (rule 8)
2. The local watcher and the shadow record. No network. P1 and P2 measured on
   the 86 local sessions. Stop if P1 misses.
3. P4 and P5 measured: analysis count on the server unchanged, caps held.
4. Hand-label 30 shadow findings, labels committed before precision is computed.
5. P3 computed. Published whether it passes or not.
6. Only then, and as its own decision: the notify endpoint and delivery.

Step 6 is last on purpose. Everything before it is observable without anyone
receiving a mail they did not ask for, and the endpoint is the only part that
cannot be taken back once someone is relying on it.
