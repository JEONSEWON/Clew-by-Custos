# Live Failure Alert: Results

Measurement against the predictions in
[`LIVE_FAILURE_ALERT_PREREG.md`](LIVE_FAILURE_ALERT_PREREG.md) §6, which its §7
requires be published whether it passes or not. Measured 2026-09-01, the day
after the pre-registration merged, on the watcher shipped in §8 step 2.

**Headline: P1 is rejected — 7 findings where 32 were predicted — and by §7
that stops the work before the hand-labelling in step 4. P2, P4 and P5 pass.
The rejection reason §7 gave for P1 is not what happened: the live path and the
batch detector agree on all 7, span for span.**

| # | Prediction | Result |
|---|---|---|
| **P1** | 32 findings on the 86 local sessions, one per session with a candidate | **REJECTED**, 7 |
| **P2** | median under 3 min from the confirmed pair's second span to the record | **PASS**, median 32.5 s, max 67.2 s |
| **P3** | precision ≥ 0.70 on 30 hand-labelled findings | **NOT MEASURED** — §7 stops before labelling |
| **P4** | server analyses caused by the fast path: 0 | **PASS**, 0 |
| **P5** | 24 candidates → 1 finding; 10 concurrent sessions → at most 3/hour | **PASS**, 1 and 3 |

## 0. The corpus, and why it had to be rebuilt

§3.2 and P1 are written against "the 86 local sessions", counted at 2026-09-01
00:25. By the time the watcher existed there were 89 files and the older ones
had grown, so the corpus the prediction names no longer existed on disk.

Claude Code session files are append-only and every event line carries a
timestamp, so the file as it stood at a past instant is a byte prefix of the
file as it stands now. Rebuilding each file at that cutoff returns **86
sessions, 32 with a structural repeat candidate (37%), min 1 · median 2 · mean
4.1 · max 24, first candidate at tool call median 98 · min 9 · max 463** —
every figure in §3.2, reproduced. Two files were truncated; three did not exist
yet. The snapshot carries a manifest with a sha256 per file, and every number
below is measured on it.

Without this the measurement would have been taken against a corpus that had
moved, and P1 would have been unfalsifiable in either direction.

## 1. P1: rejected, and not for the reason §7 named

**7 findings, not 32.** The 32 sessions hold 131 structural candidates between
them; 7 sessions hold a candidate that confirmation accepts.

§7 said a P1 miss would mean "the live path and the batch detector disagree
about the same pairs". That is not what the measurement shows:

| | |
|---|---|
| sessions where the watcher records a finding | 7 |
| sessions the batch `cascade` calls wasteful | 7 |
| the same 7 sessions | yes |
| the finding's candidate is one of that session's batch waste spans | 7 / 7 |
| and it is the *earliest* of them | 7 / 7 |
| sessions with candidates but no finding where batch still says wasteful | 0 / 25 |

The two paths agree on which sessions, which span, and which span comes first.
They agree because they run the same function: `cascade.confirm_pair` was
lifted out of the cascade loop and both paths call it.

**Where the 32 came from.** It is the count of sessions with a *structural
candidate*, which is what `_live_alert_frequency.py` measured for §3.2 — a
script whose own docstring says "confirmation can only reduce that number". The
prediction was written from the candidate table and named as a finding count.
Confirmation is the sha256 branch for tool spans, and 25 of the 32 sessions
repeat a tool call whose output came back different: a `Bash` run twice against
a changed tree, a `Read` of a file that was edited in between. Those are
repeats, not duplicates.

So P1 is rejected as written, and what it was trying to protect — that the two
paths do not disagree about a trace — holds exactly. Both halves of that
sentence are the result.

The seven, with their candidate counts: 3, 3, 4, 4, 10, 12, 24. The 25 that did
not fire: twelve had a single candidate, and the largest had 14.

## 2. P2: pass, and the poll interval is the whole latency

Median **32.5 s**, min 7.5 s, max 67.2 s, none at or above the 180 s bound.

The prereg's written expectation was that P2 was at risk from the poll interval
and not from the detection, and that is what the breakdown shows. Of the median
32.5 s, the scan is 0.36 s; the rest is waiting for the next poll at a 60-second
interval. Confirmation itself is a sha256 or two cached embeddings.

| | median | max |
|---|---|---|
| latency, repeat → record | 32.5 s | 67.2 s |
| of which scan | 0.36 s | 4.75 s |
| repeat visible after its second span started | 1.7 s | 35.4 s |

Each latency is measured by rebuilding the session file as it stood at the poll
that would have fired, ingesting that prefix for real, and adding the measured
seconds — not by modelling the scan. The poll that fires did fire in 7 / 7. The
watcher stretches its interval when a scan exceeds a quarter of it; on the polls
that fired, none did.

This is measured on 7 findings. It is a median of 7, and it is quoted as one.

## 3. P4: pass, 0

Three ways, because "we did not send anything" is the kind of claim that is
easiest to make when nothing was checked:

1. **The shipped module cannot send.** `live.py` imports `__future__`, `clew`,
   `dataclasses`, `datetime`, `json`, `pathlib`, `time`. No network module, and
   a test parses the file and fails if one appears. Verified by mutation:
   adding `import urllib.request` fails it.
2. **A real run.** `boxdawn watch --once` across the three projects configured
   on this machine: exit 0 in 2.6 s, two live sessions scanned, nothing
   recorded.
3. **The submission ledger did not move.** No file under `~/.clew` changed —
   `submitted.json` included, so no session was queued for upload as a side
   effect.

A fast path that uploads is the slow path with extra steps. This one has no
code that could.

## 4. P5: pass, both halves

**24 candidates → 1 finding.** The busiest session in the corpus records one
finding, on the earliest confirmed pair, and stops confirming there.

**86 sessions in one project at one instant → 3 findings.** Driving `sweep`
over the whole snapshot as a single project with the close rule opened wide:
86 scanned, 7 would have fired, **3 recorded, 4 held by the hourly cap**. The
cap is what the prereg said it was — the difference between an alert and a
mailing list.

## 5. What §7 requires now, and what is not claimed

§7: *"P1 misses: stop before labelling. The live path and the batch detector
must agree on the same trace before either is trusted about a new one."*

The labelling in §8 step 4 and the precision in step 5 are **not done**, and P3
is unmeasured. Delivery (step 6) is not open and was not going to be at this
stage. The watcher stays in shadow.

What is not claimed:

- **No precision figure.** 7 findings were produced; none has been labelled. It
  is not known how many are real.
- **No false-positive rate**, for the same reason.
- **Nothing about non-Claude-Code traces.** The watcher reads Claude Code
  session files; that is the only format written live on this machine.
- **No stored figure moved.** `confirm_pair` was lifted out of `cascade`
  unchanged; the full suite passes, including the frozen-manifest checks, and
  a test walks every structural candidate in a mixed trace asserting the pair
  function and the full cascade agree about each one.
- **The 7 is one machine's corpus**, one person's work, over the period those
  86 sessions cover.
