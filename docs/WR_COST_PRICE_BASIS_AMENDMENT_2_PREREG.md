# WR_cost Price Basis, Second Amendment (Pre-registration)

**Status.** Second amendment to
[`WASTE_RATE_METRIC_PREREG.md`](WASTE_RATE_METRIC_PREREG.md) §1.2, narrowing
[`WR_COST_PRICE_BASIS_AMENDMENT_PREREG.md`](WR_COST_PRICE_BASIS_AMENDMENT_PREREG.md)
after its §6 stopped the work. Per `feedback_rule_8` this document is pushed
before the code that narrows it. §2, §5 and §6 are frozen positions.

The first amendment's results stand as published
([`WR_COST_PRICE_BASIS_AMENDMENT_RESULTS.md`](WR_COST_PRICE_BASIS_AMENDMENT_RESULTS.md)).
Nothing here edits a rejected prediction.

---

## 0. Why there is a second one

The first amendment put the denominator on the billed basis and that part
worked: Corpus A's aggregate went 0.2903 → 0.9806 with `union_wr_char`
bit-identical on all 28 sessions.

It also priced **8,622 of Corpus C's 10,056 traces** that previously had a
denominator of 0.0. A zero denominator makes `WR_cost` `None`, and a `None`
trace is excluded from the aggregate — so 86% of that corpus was never in the
published figure and the change put it in. Corpus A had five such sessions of
its own. §6 called that a stop, and it was one: the corpus changed shape.

**The cause is one question with two lookups.**

| | how it finds a rate |
|---|---|
| the adapters (`ingest/claude_code.py:308`, `ingest/exgentic.py:143`, `ingest/langgraph.py:228`) | `model in input_cost_table` — **exact string** |
| `detect/context_resend._rate_and_cost_for_call` | `get_pricing(model)` — **alias and longest-prefix**, and it soft-fails to the Sonnet default |

The old denominator asked the adapter and got nothing. The numerator asked
`pricing.py` and got a rate. Pointing the denominator at the second lookup
fixed the price basis and inherited the second lookup's reach.

## 1. What this amendment does not try to fix

- **The two lookups.** They stay as they are. Making the adapters resolve
  through `pricing.py` would price traces that are unpriced today, which is the
  very change §6 stopped. It is a coverage decision with its own measurement.
- **`claude-opus-4-5` resolving to `opus-4.7`.** `resolve_pricing` matches it by
  prefix, reports `matched=True`, warns about nothing, and hands back another
  model's rate because no 4.5 entry exists. That is a real defect, it is
  recorded here, and it is not repaired by this document.
- **The stale frozen artifact.** `waste_rate_metric.RESULTS.json` no longer
  reproduces its own numerator to better than 5.2e-4. Its own item.

## 2. The narrowed rule

**A call contributes to the denominator only if the adapter priced it. How much
it contributes is the tier-aware price.**

```
rate present (input_cost_rate or cost_rate_legacy)  ->  billed, tier-aware
rate absent                                         ->  0.0, as before
```

The gate is the adapter's rate, not the tier fields. That is the whole change
from the first amendment, which gated on the tier split and so let a call with
tiers and no rate through.

Why this is the right gate: **the presence of a rate is what decided corpus
membership before any of this**, so keeping it as the gate keeps every corpus
exactly the shape it was. The price basis — the thing the amendment is
actually for — is decided separately, by whether the call recorded tiers.

## 3. What is explicitly NOT changed

Everything §3 of the first amendment listed, unchanged and restated because it
is the point: WR_char, the numerator, every stored figure, φ, N, the embedder,
the detector thresholds, the cost tables, `pricing.py`.

Plus, new here: **corpus membership.** Every trace that is excluded from a
WR_cost aggregate today is excluded after this, and no trace joins one.

## 4. The risk

Same as before and undiminished: the corrected Corpus A figure is roughly nine
times the published one, in our favour. §7 keeps measurement before
publication, and the README correction shows the old number.

Second: this rule leaves traces unmeasured rather than measuring them wrongly.
A corpus where 86% of traces have no cost figure is a coverage problem, and
this document chooses to leave it visible instead of filling it with a
substituted rate. That choice should be revisited as a coverage decision, not
absorbed into a metric fix.

## 5. Predictions

| # | Prediction | What rejects it |
|---|---|---|
| **P1** | **Corpus C: 0 newly priced, 0 substantive.** Only float-level differences remain | any newly-priced or substantive trace |
| **P2** | **Corpus B: 0 newly priced, 0 substantive**, and the float-level count is the same 1,765 as the first measurement | any newly-priced or substantive trace, or a different float-level count |
| **P3** | **Corpus A: the 5 sessions that had no denominator still have none**, and `union_wr_cost` stays `None` for them | any of the five gaining a figure |
| **P4** | the other 23 Corpus A sessions land on **exactly the figures the first measurement gave them** | any difference beyond float-level |
| **P5** | `union_wr_char` bit-identical on all 28, aggregate `0.9930314441223987` | any change |
| **P6** | the Corpus A aggregate over the 23 priced sessions is **above 0.90** | 0.90 or below |

P4 is the one that says the narrowing did nothing except stop the leak. P6 is
the number that will be published, and it is uncertain because dropping the
five changes both sums.

## 6. What would make this fail

- **P1 or P2 misses**: the gate is still not the right one. Stop; do not
  narrow a third time without understanding why.
- **P3 misses**: corpus membership moved after a document that exists to hold
  it still. Immediate stop.
- **P5 misses**: a cost change reached a byte count. Immediate stop.
- **P4 or P6 miss**: reported as measured. P6 in particular is what the README
  sentence gets rewritten around.

## 7. Order of work

1. This document, pushed before the code. (rule 8)
2. The narrowed gate, as its own commit, with a test for the case the first
   guard missed: tier fields present, rate absent, contributes 0.0.
3. Re-measure Corpus A, B and C. P1–P6 published whether they pass or not.
4. Only then the README: the `0.2903` cell and the 63-point sentence.
5. The correction shows the old number. A figure that moves nine times in our
   favour and appears without its history is indistinguishable from marketing.
