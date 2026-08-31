# WR_cost Price Basis, Second Amendment: Results

Measurement against the predictions in
[`WR_COST_PRICE_BASIS_AMENDMENT_2_PREREG.md`](WR_COST_PRICE_BASIS_AMENDMENT_2_PREREG.md)
§5. Measured 2026-09-01, the same day the amendment was written.

**Headline: all six pass, and the measurement found a second defect in the
published figure that has nothing to do with the price basis. `0.2903` divides
a numerator that includes five sessions by a denominator that excludes them —
**55.7% of that numerator has no matching denominator**. On matched pairs and
the billed basis the figure is **0.9731**. The two defects were pointing in
opposite directions, which is why neither was visible.**

| # | Prediction | Result |
|---|---|---|
| **P1** | Corpus C: 0 newly priced, 0 substantive | **PASS** · 9,691 identical, 365 float-level, 0, 0 |
| **P2** | Corpus B: 0 newly priced, 0 substantive, float-level count unchanged at 1,765 | **PASS** · exactly 1,765 |
| **P3** | Corpus A: the 5 unpriced sessions keep no denominator | **PASS** · 5 of 5 back to `None` |
| **P4** | the other 23 land on exactly the first measurement's figures | **PASS** · 23 of 23 **bit-identical**, largest relative difference 0.000e+00 |
| **P5** | `union_wr_char` bit-identical, aggregate `0.9930314441223987` | **PASS** · 28 of 28, aggregate unchanged |
| **P6** | the aggregate over the 23 priced sessions is above 0.90 | **PASS** · **0.9731** · see §2 |

## 1. The narrowing did exactly one thing

P4 is the result that says so. Every session that had a denominator before has
the same figure to the last bit, and the five that did not have one do not have
one now. The leak closed and nothing else moved.

Corpus B and Corpus C are now differences of association only — 1,765 and 365
traces respectively, at a largest relative difference of 5.57e-16 and 4.41e-16.
`0.9189` / `0.9202` and Corpus C's published figures are untouched at any
precision anyone reports them at.

## 2. The second defect, found while computing P6

P6 asked for the aggregate over the 23 priced sessions. The aggregator returned
**2.1960**, and a waste ratio above 1 is not a number, so it was traced.

`aggregate_corpus` (`field_test/diagnostics/waste_rate_metric.py:189-193`) sums
the numerator and the denominator over rows whose `excluded_reason` is unset —
and `excluded_reason` is set only when a trace has **no bytes**, never when it
has no cost. So a session with bytes and an unpriced model contributes its
waste cost to the numerator and 0.0 to the denominator.

On Corpus A that is five sessions:

| session | waste cost | denominator |
|---|---:|---:|
| `2965219c` | $2.4520 | 0.0 |
| `3be5ba0c` | **$68.0072** | 0.0 |
| `89cf9e13` | $1.9661 | 0.0 |
| `comparia` | $0.0409 | 0.0 |
| `da5d32d6` | **$110.3250** | 0.0 |

**$182.79 of numerator against no denominator — 55.7% of the total.**

### 2.1 The published figure has it too

`0.2903` was computed the same way, on the old basis:

| | numerator | denominator | ratio |
|---|---:|---:|---:|
| **as published** | 328.2175 | 1130.7605 | **0.2903** |
| matched pairs only | 145.4283 | 1130.7605 | 0.1286 |
| matched pairs, billed basis | 145.4490 | 149.4728 | **0.9731** |

The reconstruction reproduces `0.2903` to four places against the frozen
artifact's `0.2902626048478025`, so this is what that number is made of.

**Two defects pointing opposite ways.** The price basis inflated the
denominator by a median 7.71×, and the unmatched numerator inflated the top by
2.26×. They partially cancelled, and the result looked like a plausible 29%.
Neither was visible because the other was there.

### 2.2 Where this defect lives, and where it does not

- **In the publishing path.** `aggregate_corpus` is in the uncommitted
  diagnostic that produced the corpus table. That is what the README quotes.
- **Not in the per-session metric.** `compute_waste_rate` returns `WR_cost` of
  `None` when the denominator is 0, which is correct and is what §1.2 of the
  metric prereg specifies. A user running `analyze` on an unpriced trace sees
  no cost ratio, not a wrong one.
- **Not established either way for the rollup.** The stored schema keeps
  `union_waste_cost` as an absolute and the dashboard divides by
  `analyzed_cost`. Whether those two are computed over the same population is
  not checkable from this machine and is left as an open item rather than
  assumed.

## 3. What is now known about `0.2903`

It is wrong in two ways at once and the corrected figure on the same 28
sessions is **0.9731**, computed over the 23 with a price on both sides.

The README is still untouched. §7 step 4 of the first amendment says the
correction comes after the measurement, and the measurement now includes a
defect the amendment did not know about, so the sentence to be written is not
the one either document anticipated. **What gets published has to say all
three things**: the basis was mixed, the aggregate was unpaired, and the
corrected number is higher than the original in a way that a reader is entitled
to be suspicious of.

## 4. What is not claimed

- **No stored figure moved.** No ratio is stored; `union_waste_cost` is an
  absolute and is unchanged.
- **WR_char is untouched** — 28 of 28 bit-identical, aggregate unchanged.
- **Corpus B and C are untouched** in substance.
- **The aggregator is not fixed here.** It is a diagnostic, the defect is
  recorded, and fixing it changes a published number, which is its own step.
- **Nothing about the rollup or the dashboard**, per §2.2.
