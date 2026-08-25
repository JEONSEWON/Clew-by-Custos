# Session close rule — preregistration

Status: **proposed**, awaiting approval. No code ships against this until it is approved.

## 1. What this decides

Automatic submission needs an answer to one question: **when is an agent session
finished enough to measure?**

The client watches trace files that a coding agent appends to while it works. It has
to pick a moment and send. This document fixes that rule and the threshold in it,
before any implementation exists.

## 2. Why a rule is needed rather than "just send it"

Claude Code session files grow by appending. Sending the same session twice is not
caught by anything downstream:

- `run` has `unique (project_id, trace_id, payload_sha256)`. A grown file has
  **different content**, so a different `payload_sha256`, so the constraint does not
  fire.
- Both rows then aggregate into `rollup_hourly`. The waste in the first half of the
  session is counted twice.

An inflated baseline is worse than no baseline: regression alerting compares against
it, so every alert built on it is a lie. This is the same failure the alert
preregistration already refused to accept on thin evidence.

## 3. Measurement (2026-08-26)

Corpus: every Claude Code session file on the author's machine, read recursively.
**84 sessions, 39,491 inter-write gaps.**

### 3.1 Gaps between consecutive writes

| p50 | p90 | p99 | max |
|---|---|---|---|
| 0.04 min | 0.42 min | 4.56 min | 539 min (9.0 h) |

Work is near-continuous, then occasionally stops for hours. The distribution has no
natural knee below several hours.

### 3.2 How often a session resumes after N minutes of silence

This is the cost of closing too early: every such gap is a session we would have
declared finished and then watched continue.

| N | resume events | sessions affected |
|---|---|---|
| 5 min | 355 | 62 / 84 (74%) |
| 10 min | 172 | 47 / 84 (56%) |
| 15 min | 123 | 42 / 84 (50%) |
| 30 min | 77 | 36 / 84 (43%) |
| **60 min** | **34** | **24 / 84 (29%)** |
| 120 min | 16 | 14 / 84 (17%) |
| **240 min** | **2** | **2 / 84 (2.4%)** |
| 480 min | 1 | 1 / 84 (1.2%) |
| 1440 min | 0 | 0 / 84 (0%) |

### 3.3 Session length

p50 101 min · p90 500 min · max 21.8 h.

## 4. What the measurement rejected

**N = 60 minutes — rejected.** This was the working assumption before measuring. It
misfires on **29% of sessions**. An hour of silence is ordinary inside a working
session, not a sign that it ended.

**A session-end marker — does not exist.** The last line of a session file was checked
across all 84 files: its `type` is spread over eight different values
(`system` 34, `last-prompt` 20, `assistant` 20, `attachment` 3, `user` 3,
`file-history-snapshot` 2, `queue-operation` 1, `permission-mode` 1). Nothing marks
an ending. **Inactivity is the only signal available**, which is why this document is
about choosing a threshold rather than reading a flag.

## 5. The rule

**R1 — Close on inactivity.** A trace file is eligible for submission when its most
recent in-file timestamp is at least **N = 240 minutes (4 hours)** older than now.

**R2 — One submission per `trace_id`, ever.** The client keeps a local ledger of
submitted `trace_id`s and never sends one twice, whatever the file does afterwards.

**R3 — Discover recursively.** Sub-agent traces live one directory deeper
(`<project>/<session-uuid>/subagents/agent-*.jsonl`). A one-level scan misses
**13 of 84 files** on the measured corpus. Sub-agents are a place waste concentrates,
so this is not a rounding error.

### Why 240

It is the smallest listed threshold whose false-close rate is in the low single
digits (2.4%). Going to 480 or 1440 buys 1.2 points at the cost of a day's latency;
going to 120 doubles the error rate to 17%.

### What R1 + R2 cost

On the measured corpus, **2 sessions of 84 (2.4%)** would be submitted without their
final segment. That work is not measured. This is a stated, bounded loss, chosen over
the unbounded distortion that double counting produces.

## 6. Alternative considered and not taken

**Supersede in the database.** Add a `superseded_by` column to `run`, let a session be
resubmitted as it grows, and have `refresh_rollup_hourly` skip superseded rows. This
preserves append-only (nothing is deleted) and loses no tail.

Not taken now because it requires a schema change plus a rollup revision, to buy back
2.4%. Revisit if §7 shows the real loss rate is materially higher than measured here.

## 7. What would falsify this rule

Measured after automatic submission has run for **30 days**:

1. **Tail loss.** Fraction of submitted sessions whose file grew after submission.
   Predicted ≈ 2.4%. **If it exceeds 5%, R1 is rejected** and the alternative in §6 is
   implemented.
2. **Double counting.** Two `run` rows for the same `trace_id` in one project.
   Predicted **0**. **A single occurrence stops automatic submission immediately** —
   this is the failure the rule exists to prevent, so it is not graded on a scale.
3. **Latency.** Median delay between a session's last write and its `received_at`.
   Predicted ≈ 240 min plus poll interval. Recorded for the record, not a gate.

## 8. Known limits of the evidence

- **One machine, one user, one agent harness.** These gaps describe how this author
  works in Claude Code. Another person, or a CI job, or a different harness may have a
  different shape. The rule is set on the only corpus available and §7 is what
  corrects it.
- Gaps were computed from in-file `timestamp` fields, present on the message-bearing
  lines. Lines without a timestamp were skipped, so a gap is a gap between recorded
  events, not between file writes.
- 240 is a threshold on this distribution, not a property of agent sessions in
  general. It is frozen here so that a later change is visible as a change.

## 9. Dry run of the rule as written (2026-08-26)

The rule was applied to the corpus before approval, to check that the counts in §3
follow from the rule as specified rather than from the analysis that produced it.

| Check | Predicted | Dry run |
|---|---|---|
| Files found recursively (R3) | 84 | 84 |
| Files found one level deep | 71 | 71 |
| Found only by recursion | 13 | 13 |
| Sessions resuming after close at N=240 | 2 (2.4%) | 2 (2.4%) |

**One consequence the rule implies and §3 did not show: 81 of 84 sessions are
already eligible.** Everything older than four hours qualifies the moment a watcher
starts, so the first run is a backfill of the entire history on the machine, not a
trickle — on this corpus roughly 124 MB across 81 submissions.

That is not a reason to change R1, but it is a reason the implementation must not
treat the first run as ordinary:

- The backfill lands in whichever project the key names. Under Q7 the author's own
  traces go to a separate project, so this history does **not** seed the baseline
  that regression alerting will read.
- Submissions must be paced rather than fired at once. The pacing value is an
  implementation detail, not a threshold in this preregistration.
- An operator must be able to see what a first run would do before it does it.
