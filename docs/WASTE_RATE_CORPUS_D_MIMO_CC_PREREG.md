# Waste-rate Metric — Corpus D (MIMO Claude Code Traces) Pre-registration

**Status.** Pre-registration amendment to `docs/WASTE_RATE_METRIC_PREREG.md`.
Per `feedback_rule_8`, this document is pushed and a PR opened **before any
scan, measurement script, or reporting change lands**. The inclusion rules,
scope limits, and predictions in §4 and §6 are frozen positions. Adjusting
them after seeing results is not allowed.

**Nothing has been measured yet.** Everything below §3 was established by
reading the dataset and running the existing adapter for a **feasibility check
only** — trace counts, token counts, and ingest success. No waste-rate figure
has been computed for this corpus by anyone on this project.

---

## 0. Honesty preface — what this corpus is, and what it is not

The published claim rests on three corpora. The weakest by count is **Corpus A:
28 Claude Code sessions.** This amendment adds a fourth.

**What Corpus D is not:**

- **Not more of Corpus A.** Corpus A is real people doing real work. Corpus D
  is generated: the dataset card says the traces were "produced in an agentic
  coding setup" and are "generated coding-agent traces, not verified production
  patches." A larger n of a different thing is not a larger n of Corpus A, and
  this document must not be cited as though the 28 became 1,045.
- **Not multi-model.** Every trace is `mimo-v2.5-pro`. Corpus B covers 22
  models and Corpus C covers 5; Corpus D covers one. A single-model corpus
  cannot speak to model-to-model variation.
- **Not long sessions.** Measured: **p50 = 4 tool spans per trace, p90 = 9,
  max = 97.** Corpus A sessions are long real work. The standing rule "short
  sessions (under $1) — do not cite the waste rate, spread 87.29pp" applies to
  this shape, and §4.3 is how this document answers it.

**What Corpus D is:** an independent, MIT-licensed, 1,017-session corpus in the
*native Claude Code JSONL format*, carrying real per-call `usage` including
cache tiers, which the existing adapter reads without modification. It is
evidence about whether the resend footprint is an artifact of the 28 sessions
we happened to have.

## 1. The dataset

| | |
|---|---|
| Repo | `choucsan/mimo-claude-code-traces-1k` (Hugging Face) |
| License | **MIT** — verified in the dataset card frontmatter, not from a summary |
| Model | `mimo-v2.5-pro`, single |
| Files | 1,017 `.jsonl`, 44 MB on disk |
| Format | Claude Code session JSONL: `sessionId`, `parentUuid`, `uuid`, `timestamp`, `type`, `message`, `requestId`, `toolUseResult` |
| Usage fields | `input_tokens`, `cache_read_input_tokens`, `cache_creation_input_tokens`, `output_tokens` |

## 2. Feasibility check already performed (2026-08-30)

Existing adapter, no changes, `PYTHONPATH=src`:

| | |
|---|---|
| ingest success | **1,017 / 1,017 (100%)** — zero failures |
| tool spans | 5,271 total, p50 4, p90 9, max 97 |
| `llm_calls` | 4,690 total, 0 traces with an empty list |
| input tokens | 799,274,051 |
| **traces with 0 tool spans** | **158 (15.5%)** |

The 158 are surfaced by the `ingest_notes.no_tool_use_recovery` flag added in
PR #149. They are sessions where no `tool_use` ever paired with a
`tool_result`.

## 3. Pricing: this corpus cannot carry a WR_cost figure

`mimo-v2.5-pro` is **not in `src/clew/cost/pricing.py`**. `get_pricing()` falls
back to Sonnet 4.5 rates and warns:

```
pricing: unknown model 'mimo-v2.5-pro'; using default 'sonnet-4.5' (Sonnet 4.5 rates)
```

A dollar figure computed on substituted rates would describe *what this
workload would have cost on Anthropic*, not what it cost. Corpus B needed a
full pricing expansion before its `WR_cost` was allowed to exist, and the same
bar applies here.

**Pre-committed: `union_wr_cost` for Corpus D is OUT OF SCOPE.** It will not be
computed, published, or cited. If a published price list for `mimo-v2.5-pro` is
found later, adding it is a separate amendment with its own predictions — not a
follow-up edit to this one.

**In scope: `union_wr_char` and `union_sdr_at_10` only.** Both are byte-based
and rest on no price.

## 4. Frozen inclusion rules

### 4.1 The 158 zero-tool traces are EXCLUDED from the denominator

A trace with no tool call has nothing for the span-level detectors to find.
Including it contributes 0 to the numerator and a positive denominator, which
drags the aggregate down for a reason that has nothing to do with waste.
Excluding it is the treatment `excluded_reason` already gives elsewhere.

They are excluded, **counted, and reported** as `1,017 − 158 = 859 included`,
in the same `included / total` form the README table already uses for Corpus B
(`6,659 / 6,780`). A corpus that quietly drops 15% of its rows is not reporting
a rate.

### 4.2 No other exclusion

Every trace that ingests and has at least one tool span is included, however
short. No filtering by length, by task category, or by outcome. The reason is
§4.3, not indifference.

### 4.3 The short-session problem is answered by reporting, not by filtering

Dropping short sessions would raise the rate, and would be choosing the sample
after seeing its shape. Instead, pre-committed:

1. The aggregate is reported as a **union over the corpus** — one numerator,
   one denominator — not as a mean of per-session rates. A per-session mean
   lets a 2-turn session weigh as much as a 97-turn one.
2. **A per-session `wr_char` distribution is published alongside** — p10, p50,
   p90 — so a reader sees the spread rather than a single number.
3. **No per-session figure from this corpus may be cited on its own**, per the
   existing short-session rule.

## 5. What gets computed

`compute_waste_rate` as it stands, φ = 0.514345, N = 2, model
`paraphrase-multilingual-MiniLM-L12-v2`. No detector, threshold, or adapter
change is part of this amendment. If the scan turns out to need one, that is a
separate pre-registration and this one is abandoned rather than edited.

## 6. Predictions (written before the scan)

Anchors: Corpus A `union_wr_char` 0.9930 (28 long real CC sessions), Corpus B
0.9342, Corpus C 0.9233.

Reasoning for a **lower** figure than Corpus A: resend accumulates with turns.
For a session of *k* roughly equal turns the resent share tends to (k−1)/k —
0.75 at k=4, 0.89 at k=9. Corpus D's p50 is 4 tool spans. Byte-weighting pulls
the union toward the longer sessions, so the union should land above the median
session but below Corpus A.

| # | Prediction | What rejects it |
|---|---|---|
| P1 | `union_wr_char` lands in **[0.80, 0.95]** | a value outside that interval |
| P2 | It is **lower than Corpus A (0.9930)** | at or above 0.9930 |
| P3 | `union_sdr_at_10` is at least **0.85** | below 0.85 |
| P4 | per-session `wr_char` p10 is below **0.70**, showing the spread the short-session rule warns about | p10 at or above 0.70 |
| P5 | 859 traces included, 158 excluded, no ingest failures on re-run | any other count |

P1 is the one that matters. A result inside it means the resend footprint
survives a corpus we did not choose, did not generate, and cannot tune.

## 7. What would make this amendment fail

- **P1 misses low** (below 0.80): the footprint is more session-shape-dependent
  than the published claim allows. That is reported as a limit on the claim, in
  the corpus table, not buried.
- **P1 misses high** (above 0.95 on sessions whose median is 4 tool spans): the
  arithmetic in §6 is wrong, and the mechanism is not understood well enough to
  keep explaining it the way we do.
- **Ingest is not 100% on re-run**: §2 was measured on a snapshot; a
  disagreement means the snapshot is not reproducible and the corpus is not
  usable until that is explained.

Any of the three is published as-is. A missed prediction is a result.

## 8. Reproduction

```
huggingface-cli download choucsan/mimo-claude-code-traces-1k \
  --repo-type dataset --local-dir data/hf_agent_traces/mimo-cc-1k
```

Snapshot date 2026-08-30. The command above does not pin a revision, so the
scan run must record the commit sha it resolved — otherwise a later re-run that
disagrees cannot be told apart from a dataset that moved.
