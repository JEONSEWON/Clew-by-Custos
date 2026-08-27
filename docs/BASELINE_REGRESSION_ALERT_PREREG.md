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
- Time axis is `occurred_at` (`rollup_hourly.time_basis = 'occurred_at'`) —
  when the sessions ran, not when we analyzed them. Section 3 forms its
  buckets by `trace_started`, which is the same instant, and a rule that
  fires on a different axis than the one its false-positive rate was
  measured on has not been measured. `occurred_at` is a separate
  `time_basis` row rather than an overwrite, so adding it does not shift
  any baseline already computed on `analyzed_at`.
- **This axis does not exist yet.** No row with
  `time_basis = 'occurred_at'` has ever been written: the live
  `refresh_rollup_hourly` hardcodes `date_trunc('hour', r.analyzed_at)` and
  the literal `'analyzed_at'`. The alert cannot be enabled — not even in
  shadow mode — until that basis is written. That is a storage change, not
  an alert change, and it is out of scope here.
- **Late arrival is now possible.** On an `analyzed_at` axis a bucket is
  closed once the hour passes. On an `occurred_at` axis a trace uploaded
  today lands in the bucket of the day it ran, so an old bucket can change
  long after the fact — a backfill of 64 sessions rewrites months of them at
  once. Section 4 states what may fire as a result.
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
- `evaluate = newest transition only` — per `(project_id, params_key)`, only
  the transition between the two most recent qualifying buckets is
  evaluated. A bucket that changed retroactively because an old trace
  arrived late is not re-evaluated, and no transition older than the newest
  one can fire. Without this, one backfill replays months of history as
  same-day alerts. **Not measured**; like `cooldown_hours` it can only
  remove firings, never add them.
- `max_volume_ratio = 5.0` — a pair is compared only when the two windows'
  `sum(total_input_bytes)` are within 5x of each other. Above that the
  difference in waste rate is dominated by the difference in volume rather
  than by anything that changed. Derived in section 9; like the two rules
  above it can only remove comparisons, never add firings.
- A transition counts toward the 72 in section 5.1 **only if it was the
  newest transition when it was evaluated.** Otherwise a backfill inflates
  the activation counter with transitions nobody would have been alerted
  on, and the count stops meaning what section 5.1 says it means.

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
                    time_basis = 'occurred_at'   (requires that basis to be written)
evaluate          = newest qualifying transition only (see section 4)
max_volume_ratio  = 5.0         both windows' total_input_bytes within 5x of
                                each other, else the pair is not compared
                                (derived in section 9)
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

## 9. Amendment — comparability, not a bigger floor (2026-08-27)

### What this replaces

The first production series measured under this pre-registration came within
**0.0062 pp** of firing. On 27 qualifying days of one project, the largest rise
between consecutive qualifying windows was **+7.9938 pp** against a **+8.0 pp**
threshold. Nothing had regressed. The day before the rise had **3.7 MB** of
input against a 150-230 MB norm, and the "rise" was the next day being ordinary.

The obvious response was to raise `min_window_bytes` until such days stop
qualifying: 5 MB drops the two worst and cuts the largest rise to +3.736 pp at
a cost of two days out of 27. That response is wrong, and the reason it is
wrong is the same reason section 4 refuses `min_runs >= 2`.

**An absolute floor is calibrated to one user's volume.** A project whose
ordinary day is 200 MB loses only outliers at a 5 MB floor. A project whose
ordinary day is 3 MB loses **every day** and can never be alerted at all. The
floor would silence exactly the lighter users that `min_runs` was rejected for
silencing, and it would do it invisibly, because a project with no qualifying
windows produces no output to look at.

### The measurement that says what to do instead

Section 3.5 Finding 1 reported waste-rate spread by session cost and concluded
that short sessions are not quotable. That is true, and it was read here as
"low volume is unreliable". **That reading was wrong.** Splitting the same 27
days by volume band:

| band | n | `wr_char` range | spread |
|---|---|---|---|
| 0 - 5 MB | 2 | 0.9011 - 0.9107 | **0.96 pp** |
| 5 - 30 MB | 3 | 0.9542 - 0.9749 | 2.08 pp |
| 30 - 100 MB | 6 | 0.9857 - 0.9934 | **0.77 pp** |
| 100 - 300 MB | 10 | 0.9852 - 0.9936 | 0.84 pp |
| 300 MB and up | 6 | 0.9816 - 0.9954 | 1.38 pp |

Within a band the metric is tight — 0.77 to 2.08 pp. The **9.43 pp** spread
across the series is produced entirely by comparing across bands. A 1.2 MB day
and a 3.7 MB day agree with each other to within 0.96 pp, which is tighter than
the largest days agree with each other. Low volume is not noisy; it sits at a
different level, because re-sent context accumulates with session length and a
short day has not accumulated any.

So the defect is not that small windows are unmeasurable. It is that the rule
compares them with large ones.

### Deriving the ratio

Every pair of the 27 days (351 pairs), bucketed by the ratio of the larger
window's bytes to the smaller's:

| volume ratio | pairs | `abs delta wr` p50 | p90 | max |
|---|---|---|---|---|
| 1 - 1.5x | 66 | 0.208 pp | 0.875 pp | 1.196 pp |
| 1.5 - 2x | 44 | 0.219 pp | 0.914 pp | 2.106 pp |
| 2 - 3x | 60 | 0.262 pp | 1.183 pp | 4.347 pp |
| 3 - 5x | 55 | **0.344 pp** | 1.566 pp | 3.921 pp |
| 5 - 10x | 44 | **1.359 pp** | 3.643 pp | 6.424 pp |
| 10 - 30x | 37 | 2.306 pp | 7.863 pp | 8.268 pp |
| 30x and up | 45 | 8.358 pp | 9.237 pp | 9.430 pp |

The median holds between 0.21 and 0.34 pp from 1x through 5x and then
**quadruples**. That is the volume term becoming visible, and it is where the
cut belongs: `max_volume_ratio = 5.0`. The value is read off this table rather
than chosen for roundness; 10x would also keep the largest rise under the
threshold, but at 10x the volume term is already the larger part of the signal.

Applied to the consecutive qualifying transitions of the same series:

| max_volume_ratio | transitions kept | largest rise |
|---|---|---|
| 3x | 10 of 26 | +1.336 pp |
| **5x** | **16 of 26** | **+1.336 pp** |
| 10x | 19 of 26 | +1.773 pp |
| none (as pre-registered) | 26 of 26 | **+7.994 pp** |

### Why this does not disturb the section 5 verdict

The rule only removes pairs from consideration. It cannot create a firing that
did not exist, so section 3.5's `0/46` and its Clopper-Pearson upper bound of
**7.7%** remain a valid upper bound on the no-change firing rate under it --
the same argument section 4 makes for `cooldown_hours`. No re-run of the pilot
is needed to keep the shadow-mode decision honest.

**What it does cost is time.** Fewer qualifying transitions per day of use
means the 72 reviewed transitions of section 5.1 accumulate more slowly -- on
this series, 16 where 26 were available, so roughly 1.6x as long. That is the
price of not counting comparisons that were never meaningful, and it is paid in
schedule rather than in correctness.

### Limits, stated

- **One project, 30 days, one author's traces.** The ratio is derived from a
  single usage pattern. A user whose volume swings by 10x daily as a matter of
  course would find most of their days uncompared, and nothing here would
  reveal that. This value is to be re-derived when a second project's series
  exists, and the same objection that killed the absolute floor applies to this
  ratio if it turns out to be calibrated to one rhythm.
- **The low bands are thin.** `0 - 5 MB` has n = 2 and `5 - 30 MB` has n = 3.
  The claim those bands support -- that low volume is tight rather than noisy --
  is consistent with the mechanism and with the cost-banded table of section
  3.5, but two points are two points.
- **The pilot corpus was not re-measured under the rule.** The argument above
  says it does not need to be for the bound to hold; it does mean the tables in
  section 3.5 describe the rule as originally pre-registered, not as amended.

### The dashboard follows

Section 3.5 Finding 1 (c) already binds the chart to volume-weighted
aggregation. The same applies here: a chart that draws a line between two
windows the alert would not compare shows the user a movement the alert does
not believe in. Whatever connects points on the series honours
`max_volume_ratio` as well.
