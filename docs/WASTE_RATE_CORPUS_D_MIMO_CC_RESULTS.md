# Waste-rate Metric — Corpus D (MIMO Claude Code Traces) Results

Scan of the corpus registered in
[`WASTE_RATE_CORPUS_D_MIMO_CC_PREREG.md`](WASTE_RATE_CORPUS_D_MIMO_CC_PREREG.md),
run 2026-08-30 after that document was merged and before any of its numbers
were seen.

**Headline: prediction P1 missed, low, by 0.0007.** The prereg named
`union_wr_char ∈ [0.80, 0.95]`; the scan returned **0.7993**. It is reported
here as a miss rather than rounded to the boundary it fell short of.

## 1. Provenance

| | |
|---|---|
| Dataset | `choucsan/mimo-claude-code-traces-1k` |
| Revision | `39cc3fc3ed608fff800220445bad9eb1738516f8` |
| Dataset last modified | 2026-08-06 09:34 UTC |
| License | `mit` (from the Hub's own `cardData`) |
| Scan date | 2026-08-30 |
| Detector params | φ = 0.514345, N = 2, `paraphrase-multilingual-MiniLM-L12-v2` |
| Script | `field_test/diagnostics/corpus_d_mimo_scan.py` |

The scan imports `field_test/diagnostics/waste_rate_metric.py`'s rate tables,
constants, row shape, aggregation and bootstrap rather than restating them, so
Corpus D is computed by the arithmetic that produced the published Corpus A and
B figures.

## 2. Predictions vs. observed

| # | Prediction | Observed | |
|---|---|---|---|
| **P1** | `union_wr_char` in **[0.80, 0.95]** | **0.7993** | ❌ **MISS (low)** |
| P2 | lower than Corpus A (0.9930) | 0.7993 | ✅ |
| P3 | `union_sdr_at_10` ≥ 0.85 | **0.9441** | ✅ |
| P4 | per-session `wr_char` p10 < 0.70 | **0.1722** | ✅ |
| P5 | 859 included / 158 excluded / 0 ingest failures | 859 / 158 / 0 | ✅ |

**4 of 5 passed. P1 is the one that mattered, and it missed.**

95% two-sided bootstrap on `union_wr_char`: **[0.7776, 0.8168]**, median
0.7983. The interval straddles the 0.80 boundary, so the true value may well
sit inside the predicted range — but P1 was written about the point estimate,
and the point estimate is outside it. The prereg does not have a clause that
lets a confidence interval rescue a missed point prediction, and adding one now
would be the thing pre-registration exists to prevent.

## 3. What the miss says

The prereg's §7 named the consequence in advance: *"the footprint is more
session-shape-dependent than the published claim allows. That is reported as a
limit on the claim, in the corpus table, not buried."*

The scan says exactly that, and says it precisely. Splitting the included
traces by tool-call count:

| tool spans per trace | traces | `union_wr_char` (byte-weighted) | share of corpus bytes |
|---|---:|---:|---:|
| 1–2 | 244 | **0.3487** | 1.8% |
| 3–5 | 337 | **0.6453** | 16.4% |
| 6–10 | 218 | **0.7767** | 31.4% |
| 11+ | 60 | **0.8802** | 50.3% |

The rate rises monotonically with session length, which is the (k−1)/k
arithmetic in prereg §6 doing what it was expected to do. The mechanism is not
in question. What the miss corrects is the reach of the headline: **on short
sessions the resend footprint is materially smaller**, and a corpus whose median
session is four tool calls lands below the range predicted from corpora made of
long ones.

The per-session distribution makes the same point without any bucketing:

| p10 | p50 | p90 |
|---:|---:|---:|
| 0.1722 | 0.6297 | 0.8104 |

A per-session median of 0.63 against a corpus union of 0.80 is the byte
weighting at work — the 60 traces with 11+ tool calls carry 50.3% of the bytes.
This is why prereg §4.3 pre-committed to publishing the union *and* the spread,
and why no single-session figure from this corpus may be cited.

## 4. `union_wr_cost` — confirmed uncomputable, as pre-committed

Prereg §3 put `union_wr_cost` out of scope because `mimo-v2.5-pro` is absent
from the pricing table. The scan confirms this was not merely a policy choice:
the summed `total_input_cost` across all 859 included traces is **0.0**, so the
ratio is `None`, not a number that happened to be wrong. There is no dollar
figure to suppress.

## 5. Corpus composition (as scanned)

| | |
|---|---|
| files | 1,017 |
| ingest failures | **0** |
| excluded, no tool span (§4.1) | **158** |
| included | **859** |

The 158 were identified by `ingest_notes.no_tool_use_recovery`
(PR #149). Without that field they would have entered the aggregate as
"no waste detected" — 15.5% of the corpus contributing a zero numerator
against a positive denominator for a reason unrelated to waste.

## 6. What this corpus may and may not be cited as

Repeating prereg §0 because the numbers now exist and a citation is now
possible:

- **May be cited as**: an independent, MIT-licensed, 859-trace corpus that we
  did not choose, generate, or tune, on which the union byte-based resend share
  is **0.7993** and 94.4% of sessions exceed the 10% threshold.
- **May not be cited as**: more of Corpus A (these are generated traces, one
  model, short sessions); evidence about cost or dollars (§4); or as a
  per-session figure (§4.3).
- **The `[0.80, 0.95]` prediction must not be quoted as though it held.**

## 7. Effect on the published claim

The README corpus table gains a row and a qualifier. The three existing corpora
are unchanged — nothing in this amendment touched a detector, a threshold, or
an adapter. What changes is that the range of published `union_wr_char` values
now runs from **0.7993** (Corpus D, median 4 tool calls) to **0.9930**
(Corpus A, long real sessions), and the honest reading of the spread is session
length, not disagreement between corpora.
