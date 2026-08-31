# WR_cost Price Basis (Amendment · Pre-registration)

**Status.** Amendment to [`WASTE_RATE_METRIC_PREREG.md`](WASTE_RATE_METRIC_PREREG.md)
§1.2. Per `feedback_rule_8` this document is pushed and PR-opened **before any
code lands**. The decision in §2, the exclusions in §3, the predictions in §5
and the stop conditions in §6 are frozen positions. Adjusting them after seeing
results is not allowed.

---

## 0. What is wrong

**`union_wr_cost` divides a number priced one way by a number priced another.**

| | what it computes | where |
|---|---|---|
| numerator `resent_cost` | resent tokens × the **tier-aware effective rate** — cache reads at the cache-read price | `detect/context_resend.py:169-176`, `:330` |
| denominator `total_input_cost` | **every** input token × the **base input rate** | `metrics/waste_rate.py:111-116` |

The denominator's token count is itself the sum of all three tiers
(`ingest/claude_code.py:300-304`: uncached + cache_read + cache_write), and the
rate applied to it is the flat base rate (`:307-309`). So the denominator is
what the session *would have* cost with no caching, and the numerator is part of
what it *did* cost.

The ratio is therefore "billed waste ÷ the counterfactual bill", which is not a
quantity anyone asked for.

**Size, re-measured 2026-09-01 on the three Corpus A sessions measured on
08-30, and identical to that day's figures:**

| trace | billed input | denominator as-is | ratio | `union_wr_cost` | on one basis |
|---|---:|---:|---:|---:|---:|
| `07b57159` | $5.8620 | $53.4336 | 9.12× | 0.1062 | **0.9676** |
| `09d9abe9` | $5.1486 | $41.5352 | 8.07× | 0.1164 | **0.9391** |
| `0ca72c0c` | $0.4294 | $2.8606 | 6.66× | 0.1010 | **0.6726** |

## 1. Why the original pre-registration does not settle this

§1.2 defines the denominator as `trace.total_input_cost` and stops there. It
names no price basis, because when it was written there was one rate per model
and no tier split existed to disagree about. The mismatch arrived with cache
tiers and no document had to be violated for it to happen.

This amendment exists to fix the definition, not to correct a deviation from
it.

## 2. The decision: both sides on what was billed

**The denominator becomes the sum of the tier-aware input cost of every LLM
call — the same function the numerator already prices with.**

```
WR_cost = Σ waste_cost(span)  /  Σ billed_input_cost(call)
```

The question the metric then answers is: **of what you were charged for input,
how much went to sending the same thing again.** That is the sentence the number
has always been quoted as meaning.

Why not the other direction — pricing the numerator at the base rate too, so
both sides are the no-cache counterfactual:

- The counterfactual is a good number for a different question ("what is
  caching saving me"), and it is recoverable at any time from the same tier
  fields. Nothing is lost by not making it the headline.
- The live dashboard already divides by `analyzed_cost`, which is billed. One
  of the two has to move to make a page internally consistent, and moving the
  metric toward the money the user actually paid is the direction that needs no
  footnote.
- A waste ratio whose denominator counts money nobody spent will read as
  inflated the moment anyone checks it against an invoice.

## 3. What is explicitly NOT changed

- **WR_char.** Bytes have no price basis. Numerator, denominator and every
  published `union_wr_char` stay exactly as they are.
- **The numerator.** `resent_cost`, `waste_cost` and the union tie-break rule
  (§4.2) are untouched. Only the denominator moves.
- **Every stored figure.** `union_waste_cost` is an absolute amount and does not
  change. No ratio is stored — `0001` §0.3 forbids it, which is why this defect
  never reached the database — so no rollup, no alert rule and no `run` row is
  affected. Rule A is `wr_char_rise`; rule B is an absolute dollar cap.
- **φ, N, the embedder, the detector thresholds, the cost tables.**
- **The pricing source of truth.** `cost/pricing.py` is not edited.

## 4. The risk this carries, named before the measurement

**The correction moves our own number upward, by a lot.** 0.1062 becomes 0.9676
on one session. That is the most suspect direction a correction can have, and
the reason the order in §7 is measurement first and publication second.

Two places in the README are affected, and the second is the one that matters:

- `README.md:246`, the Corpus A row: `union_wr_cost` **0.2903**.
- `README.md:257`, which reads *"**Corpus A 29%** — dollars leaked after
  Anthropic prompt caching is applied ... **Corpus B 92%** — dollars leaked if
  the caller does not use prompt caching ... The 63-percentage-point gap is the
  caching lever's leverage on the same Context Resend detector."*

That sentence describes the numerator correctly and the denominator not at all.
The leak is after caching; the total it is divided by is before. And Corpus B's
adapter sets `input_tokens_cache_read = 0` (`ingest/toolathlon.py:222-224`), so
Corpus B is already on one basis and does not move — which means **the two
corpora were never compared on the same footing, and part of that 63-point gap
is the mismatch rather than the lever**. How much is what §5 measures. The
sentence is not repaired by guessing at the split.

## 5. Predictions (written before measuring anything but the three above)

| # | Prediction | What rejects it |
|---|---|---|
| **P1** | on all 28 Corpus A sessions the ratio `denominator_as_is / billed` is **≥ 1.0** | any session below 1.0 — cache writes cost 1.25× base, so a write-heavy session could bill more than the counterfactual, and if that happens the word "counterfactual" is wrong |
| **P2** | on all 28, `union_wr_cost` **rises**, and by more than 2× on at least 24 | any session where it falls, or fewer than 24 above 2× |
| **P3** | `union_wr_char` is **bit-identical** on all 28 | any change at all |
| **P4** | **Corpus B is bit-identical.** Every Toolathlon trace's two denominators are exactly equal, so `0.9189` / `0.9202` do not move | any difference |
| **P5** | **Corpus C is bit-identical**, for the same reason (`ingest/exgentic.py:176-177` sets the tier fields to None) | any difference |
| **P6** | the published Corpus A aggregate **0.2903 rises above 0.70** | 0.70 or below |

P6 is the one that decides how the README sentence gets rewritten, and it is
genuinely uncertain: one of the three sessions above lands at 0.6726.

**Written expectation, not a prediction:** P4 and P5 are the ones this document
is least worried about and most needs, because they are what says the defect is
Claude-Code-shaped rather than metric-wide.

## 6. What would make this fail

- **P3 misses**: immediate stop. A cost-basis change that moves a byte count
  means the change reached somewhere it had no business reaching.
- **P4 or P5 misses**: stop and re-scope. Two corpora quoted in published
  results move, and this stops being an amendment and becomes a re-measurement
  of everything.
- **Any stored figure moves**: immediate stop, per §3.
- **P1 misses**: the direction of the mismatch is not what §0 says it is, and §2
  is argued from that direction. Re-argue before proceeding.
- **P2 or P6 miss**: not a stop. They are reported as measured, and §7 step 5
  rewrites the README sentence around whatever they say.

## 7. Order of work

1. This document, merged, before any code. (rule 8)
2. The denominator change, as its own commit, with tests.
3. Re-measure Corpus A, B and C. P1–P6 computed and published whether they pass
   or not, in the same place as the rejected P1 of the live alert and the
   `unverified_edit` kill.
4. Only then, the README: the `0.2903` cell and the 63-point sentence, each
   corrected to what step 3 measured.
5. The correction is stated as a correction, with the old number visible. A
   figure that moves 9× in our favour and appears without its history is
   indistinguishable from marketing.
