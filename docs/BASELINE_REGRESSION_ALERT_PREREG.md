# Baseline Regression Alert — Pre-registration

Status: **draft, unapproved.** No code is written against this document
until it is approved (`feedback_rule_8_pr_route`).

## 0. Honesty preface (what this alert is and is not)

Every number this project publishes so far describes **one trace**: this
session wasted 66.0% of its input bytes, this session cost $2.52 of which
$1.66 was re-sent context. The storage layer (M2 Phase 1) makes a second
kind of statement possible:

> "This project's waste rate moved from X to Y, and that move is larger
> than this project's own normal variation."

That is a **judgment**, not a measurement — it needs a threshold, and a
threshold invented after seeing the data is not defensible. Hence this
prereg.

**Not claimed by this document:**

- That a regression alert identifies a *cause*. It says the number moved,
  not why. Attribution to a deploy, a prompt change, or a model swap is
  out of scope.
- That the alert predicts anything. `reference_args_only_kill` killed
  prediction-then-block at precision 0.6333; nothing here revives it.
  This fires **after** the runs are recorded.
- That an absence of alerts means an absence of waste. Waste rate is high
  and stable in every corpus measured (0.92–0.99 WR_char). A project can
  burn most of its input tokens on re-sent context every single day and
  never trigger a regression alert. **The alert is about change, and the
  steady-state number is the other product surface.**

## 1. Why a multiplicative threshold on the ratio is rejected

The obvious rule — *"alert when waste rate is k× the baseline"* — cannot
work on our primary metric, because the metric is bounded at 1.0 and the
measured values sit near the ceiling:

| Corpus | Sessions | WR_char |
|---|---|---|
| A (Claude Code) | 28 | 0.9926 |
| B (Toolathlon) | 6,780 | 0.9340 |
| C (Exgentic) | 10,056 | 0.9233 |

At 0.9926, `k = 1.5` demands a waste rate of 1.49, which does not exist.
Even `k = 1.05` is unreachable. A rule that can never fire is worse than
no rule: it reads as coverage.

Three candidate signals replace it. Which ones ship is decided by §3's
measurement, not by preference:

- **S1 — `wr_char` percentage-point rise.** `wr_char(current) −
  wr_char(baseline) ≥ d1`. No ceiling problem; `d1` must come from the
  project's own variation.
- **S2 — `wr_cost` percentage-point rise.** Same form. Listed separately
  because `wr_cost` is environment-dependent (`reference_tiktoken_undeclared`)
  and spans 0.29–0.94 across corpora, i.e. it is *not* pinned to the
  ceiling and may carry more signal.
- **S3 — waste cost per run, multiplicative.** `waste_cost/run_count`
  is unbounded, so `k` is meaningful again. Weakness: it moves with the
  work itself — a longer session costs more without being less efficient.
  S3 is therefore specified as a *dollar* alert, not an efficiency alert,
  and must be labelled as such wherever it surfaces.

## 2. Comparison unit (frozen)

- Alerts are computed **per `(project_id, params_key)`**. `params_key`
  already keys `rollup_hourly` on `phi`, `n_window`, `embed_model`,
  `analyzer_version`; comparing across it would report an analyzer change
  as a waste change. Measured precedent: `waste_span_count` 31→9 from the
  absence-sentinel amendment and `waste_ratio` 0.667254→0.659536 from
  declaring tiktoken. **Two analyzer changes moved the numbers in one day.**
- Time axis is `analyzed_at` (`rollup_hourly.time_basis = 'analyzed_at'`),
  matching Q4. When `occurred_at` becomes the axis it is a new
  `time_basis` row, not an overwrite, so baselines do not silently shift.
- Ratios are always recomputed as `sum(numerator)/sum(denominator)` over
  the window. Averaging per-bucket ratios is prohibited: the mean of
  ratios is not the ratio of sums. (This is why 0.5.3 added
  `union_waste_bytes`, `union_waste_cost`, `total_input_cost`.)

## 3. Method — measure the noise floor before choosing thresholds

The false-positive floor of any threshold is how much the metric moves
**when nothing changed**. That is measurable today without new code:

1. Take every session of a single real project (one codebase, one
   toolchain) from `~/.claude/projects`.
2. Analyze each at a fixed `params_key` (0.5.3, frozen phi/n/model).
3. Order by `trace_started` and form daily buckets.
4. Report, per project: session count, per-day session count, and the
   distribution of day-over-day deltas for S1/S2/S3.
5. For each candidate threshold, count what fraction of day transitions
   would have fired. **That fraction is the empirical false-positive
   rate**, because no deliberate regression was introduced.

Thresholds are then set so the measured firing rate on this
no-change stream lands under the §5 ceiling — and the chosen values are
frozen here before any alerting code exists.

## 3.5 Pilot measurement — executed during drafting (2026-08-24)

**Disclosure:** the measurement below was run *while this document was being
drafted*, and section 6's values were chosen with it in view. This is a design
pre-registration for the production evaluation, not a post-hoc validation of
numbers that were already shipping. Nothing in section 6 has run against a user.

Corpus: **4 real projects** from `~/.claude/projects` (one project = one
codebase = one baseline), all sessions under 5 MB, analyzed at a single frozen
`params_key` (0.5.3, frozen phi/n/model). 66 sessions, 54 day-buckets,
**50 consecutive-day transitions**. No regression was introduced, so every
firing is a false positive by construction.

| project | sessions | day buckets |
|---|---|---|
| clwe | 33 | 26 |
| nfc | 13 | 11 |
| web | 12 | 10 |
| shop | 8 | 7 |

### Finding 1 — waste rate is near-constant where the money is

Within a single project, `wr_char` by session size:

| session `analyzed_cost` | n | `wr_char` range | spread |
|---|---|---|---|
| under $1 | 3 | 0.0124 - 0.8853 | **87.29 pp** |
| $1 - $5 | 7 | 0.8543 - 0.9696 | 11.54 pp |
| $5 and up | 7 | **0.9841 - 0.9924** | **0.83 pp** |

Re-sent context compounds with session length, so a short session has not
accumulated any. Consequences: (a) regression detection is feasible, because
the metric is stable exactly where the spend is; (b) **a per-session waste
rate from a short session must not be quoted** — the same project produces
1% and 89%; (c) a dashboard that plots small and large sessions on one axis
produces a sawtooth. Volume-weighted aggregation (sum over sum, which
`rollup_hourly` already does) is not a preference, it is required.

### Finding 2 — the gate is volume, not run count

12 of 14 days in the largest project have **exactly one run**. A
`min_runs >= 2` gate would silence a solo developer entirely. A minimum
**input-byte** floor on the window is what suppresses the noise:

| window floor | transitions | S1 abs delta p50 | p90 | max |
|---|---|---|---|---|
| none | 50 | 0.95 pp | 17.08 pp | 24.14 pp |
| 1 MB | 46 | 0.83 pp | 3.04 pp | 7.84 pp |
| 3 MB | 42 | 0.58 pp | 1.83 pp | 2.37 pp |

### Finding 3 — firing rates, rise-only (the actual alert semantics)

A *fall* in waste rate is good news and is not alerted. Of 50 transitions,
21 were rises. Clopper-Pearson 95% two-sided upper bounds
(`reference_clopper_pearson_convention`):

| floor | +3 pp | +5 pp | +8 pp | +10 pp |
|---|---|---|---|---|
| none | 7/50 (upper 26.7%) | 6/50 (24.3%) | 4/50 (19.2%) | 3/50 (16.5%) |
| 500 KB | 4/47 (20.4%) | 3/47 (17.5%) | 1/47 (11.3%) | 1/47 (11.3%) |
| **1 MB** | 3/46 (17.9%) | 2/46 (14.8%) | **0/46 (7.7%)** | 0/46 (7.7%) |
| 2 MB | **0/42 (8.4%)** | 0/42 (8.4%) | 0/42 (8.4%) | 0/42 (8.4%) |

`wr_cost` (S2) stays loud at every floor: 37.0% of transitions move 10 pp or
more at the 1 MB floor, 28.6% at 3 MB. `waste_cost/run` (S3) moved by up to
**44,042x** with no floor and 16x at the 1 MB floor, firing on 33% of
transitions at 2x.

### Finding 4 — the sample cannot certify the section 5 bar

With zero observed firings, the Clopper-Pearson upper bound is
`1 - 0.025^(1/n)`, so **n >= 72 transitions** are required for the bound to
reach 5%. The best configurations produce 0 firings on **46** and **42**
transitions — upper bounds of 7.7% and 8.4%. The point estimate is 0.0%; the
bound is not under 5%.

This is the LLM-judge failure verbatim: 52.20% on n=5 became 31.73% on
n=48. A point estimate on a small sample is not a GO.

## 4. Minimum sample and noise suppression (frozen)

- **No `min_runs` gate.** Section 3.5 Finding 2: it would silence
  single-session days, which are the norm.
- `min_window_bytes = 1_048_576` — a day bucket qualifies only if
  `sum(total_input_bytes)` is at least 1 MB. Both the current and the
  previous qualifying bucket must clear it; non-qualifying days are skipped,
  not zero-filled.
- `cooldown_hours = 24` — one alert per `(project_id, params_key, signal)`
  per 24 h. **Not measured** — a default chosen so a sustained shift reports
  once. It cannot raise the false-positive rate above section 3.5's
  measurement; it can only lower it.

## 5. Go/No-go (frozen)

GO requires the **Clopper-Pearson 95% two-sided upper bound** on the
no-change firing rate to be at most 5% — not the point estimate. Stated as
the bound because section 3.5 Finding 4 is precisely a case where the point
estimate (0.0%) and the bound (7.7%) disagree about whether the rule is quiet.

**Verdict on the pilot:**

| signal | best configuration | result | verdict |
|---|---|---|---|
| S1 `wr_char` rise | 1 MB floor, +8 pp | 0/46, bound **7.7%** | **NO-GO for notification** — ships in shadow mode (5.1) |
| S2 `wr_cost` rise | any | 17% or more of transitions at every floor | **NO-GO.** Not an alert. |
| S3 `waste_cost/run` | any | 33% at 2x, max 44,042x | **NO-GO.** A dollar figure, never an alert. |

### 5.1 Shadow mode (frozen)

S1 ships **recorded but not delivered**: the evaluation runs, the firing is
stored, and nobody is notified. Notification turns on only when, in
production data at the frozen configuration, **72 or more qualifying
transitions** have accumulated whose fired cases have been reviewed and the
Clopper-Pearson upper bound on genuine false positives is at most 5%.

Production transitions are not a no-change stream — a firing there may be a
real regression. So the review is manual and per-case, and a firing counts
against the bound only when the reviewer finds no change that explains it.
That review, and the count, are what a later amendment reports.

**Why this is not stalling:** the dashboard's value — the time series —
does not depend on the alert. Shipping the chart while the alert stays dark
costs the user nothing, and the storage layer generates exactly the data the
threshold needs.

## 6. Frozen values

```
signal            = S1 only  (wr_char, rise only; a fall is not alerted)
metric            = sum(union_waste_bytes) / sum(total_input_bytes) over the window
                    (never the mean of per-bucket ratios)
window            = one day bucket of rollup_hourly, per (project_id, params_key)
                    time_basis = 'analyzed_at'
threshold         = +8.0 pp vs the previous qualifying window
min_window_bytes  = 1_048_576   (both windows must qualify)
min_runs          = none        (see section 3.5 Finding 2)
cooldown_hours    = 24          per (project_id, params_key, signal)
delivery          = shadow mode (5.1) - recorded, not delivered
activation        = 72+ reviewed qualifying transitions, CP95 upper at most 5%
```

Pilot at this configuration: **0 firings / 46 transitions**, CP95 upper
7.7%. `wr_cost` and `waste_cost/run` are excluded entirely.

## 7. Backout plan

Alerts are a read path over `rollup_hourly`. Backing out is deleting the
evaluation, not migrating data; no stored row changes meaning. The
rollup itself stays.

## 8. Explicit non-commitments

- No alert channel is specified here (email, Slack, webhook). Channel is
  a product decision; this document only fixes *when* something is worth
  saying.
- No auto-remediation. The chain is monitor → detect → notify; the fix
  step is a separate prereg with its own evidence bar.
