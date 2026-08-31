# WR_cost Price Basis: Results

Measurement against the predictions in
[`WR_COST_PRICE_BASIS_AMENDMENT_PREREG.md`](WR_COST_PRICE_BASIS_AMENDMENT_PREREG.md)
§5, which its §6 requires be published whether it passes or not. Measured
2026-09-01, the same day the amendment merged.

**Headline: P5 is rejected and the work stops there, by §6. The denominator
change does what §2 said on Corpus A — the aggregate goes 0.2903 to 0.9806 and
WR_char does not move a digit — but on Corpus C it prices 8,622 of 10,056
traces that had no price at all, at a rate substituted for four models missing
from the cost table. That is a change of population, not of arithmetic, and
this amendment did not register it.**

| # | Prediction | Result |
|---|---|---|
| **P1** | ratio ≥ 1.0 on all 28 Corpus A sessions | **PASS** on all 23 that had a denominator · min 1.415 · median 7.71 · max 9.12 |
| **P2** | all 28 rise, 24+ above 2× | **REJECTED as written** · 22 of 23 · the exception has zero waste |
| **P3** | `union_wr_char` bit-identical | **PASS**, 28/28 |
| **P4** | Corpus B bit-identical | **REJECTED on the letter** · 1,765 of 6,780 differ by ≤ 5.57e-16 · 0 substantive |
| **P5** | Corpus C bit-identical | **REJECTED** · 8,622 of 10,056 newly priced |
| **P6** | Corpus A aggregate above 0.70 | **PASS**, 0.2903 → **0.9806** · and not clean, see §5 |

## 1. What the change does when it works (P1, P2, P6)

On Corpus A the denominator falls by a **median of 7.71×** (min 1.415, max
9.12) and `union_wr_cost` rises with it. The aggregate goes **0.2903 → 0.9806**:
of what these 28 sessions were charged for input, 98% went to sending context
that had already been sent.

`union_wr_char` is **bit-identical on all 28** and the aggregate stays
0.9930314441223987. Bytes have no price basis and the change did not reach
them, which is what P3 was for.

**P2 is rejected as written and the reason is a session with no waste.**
`4c09dfa9` has `union_waste_cost` of exactly 0.0, so its ratio is 0/x either
way and it neither rose nor doubled. Of the 22 sessions that have any waste,
**all 22 rose and all 22 rose by more than 2×**. The prediction should have
said "every session with nonzero waste"; it did not, so it is reported as
rejected.

## 2. P4: rejected by floating point, not by arithmetic

Corpus B, all 6,780 traces: **5,015 identical, 1,765 different, 0 substantive.**
The largest relative difference anywhere is **5.57e-16** — one unit in the last
place.

The cause is association, not pricing:

```
tokens * (rate_per_mtok / 1e6)      the old denominator
(tokens * rate_per_mtok) / 1e6      the tier function
```

Same number, different float. Toolathlon's figures (`0.9189` / `0.9202`) do not
move at any precision anyone reports them at. P4 was written as "exactly equal"
and "exactly" is what it lost on.

## 3. P5: rejected, and this is the real one

Corpus C, all 10,056 rows: **1,069 identical, 365 float-level, and 8,622 newly
priced.** Newly priced means the old denominator was **0.0** and the new one is
not.

A denominator of 0 makes `WR_cost` `None`, and a `None` trace is **excluded from
the aggregate**. So 86% of Corpus C was never in the published WR_cost figure,
and the new denominator puts it in.

It gets there because `_rate_and_cost_for_call` resolves a model through
`get_pricing`, which **soft-fails to the Sonnet 4.5 default** for a model it
does not know. Four models in Corpus C are not in the cost table:

```
DeepSeek-V3.2 · Kimi-K2.5 · claude-opus-4-5 · gpt-5.2-2025-12-11
```

Their traces had no price. Now they have Sonnet's.

**This is not the defect the amendment set out to fix.** §0 is about two price
bases for one ratio; this is about which traces are in the corpus at all. §3
said the cost tables are not changed, and pricing four previously unpriced
models is a change to the cost table by another route.

Corpus A has the same problem in miniature: **5 of its 28 sessions** were
unpriced and are now priced, which is why §5 below says P6 is not clean.

The commit already carried a guard against exactly this and it was not enough.
Calls with **no tier split** keep the old arithmetic, and a test states the
rule. But Exgentic fills the tier fields as uncached-only, so its calls *have* a
tier split while having no rate — a case the guard did not cover and the
measurement found.

## 4. What did not come from this change

**The numerator moved on 19 of 28 Corpus A sessions**, by a relative 1.5e-4 to
5.2e-4. That is not float noise and it needed explaining.

It is not this commit. Reverting the denominator branch and re-measuring
`4222016d` gives `12.394226908855401` — **today's number, not the frozen
artifact's 12.389121**. The numerator path is identical with and without the
change.

The frozen `waste_rate_metric.RESULTS.json` predates several merged changes to
pricing and to the cascade, and it has drifted by about 0.04% on the numerator
since. **That is an open item of its own**: a frozen artifact that no longer
reproduces is a manifest that has stopped being a manifest. It is named here
rather than fixed here.

## 5. What is not claimed

- **P6 is not clean.** 0.9806 includes 5 sessions that entered the aggregate
  through the §3 defect. The number after that is fixed will be different, and
  the README is not touched until then — §7 step 4 does not begin.
- **Nothing is published yet.** The `0.2903` cell and the 63-point sentence in
  `README.md` stay as they are.
- **No stored figure moved.** No ratio is stored, and `union_waste_cost` is an
  absolute the change does not touch.
- **Corpus B is unaffected in substance** and Corpus C's *existing* figures are
  unaffected too — what changes is which traces would be counted next time.

## 6. What §6 requires now

§6: *"P4 or P5 misses: stop and re-scope. Two corpora quoted in published
results move, and this stops being an amendment and becomes a re-measurement of
everything."*

The work stops. The denominator change is committed and not merged, and the
README is untouched.

The narrow repair this points at — leave a call with no resolvable rate
contributing 0.0, tier split or not, so the corpus keeps its shape — is a
second amendment and not a correction to this one. It is written separately so
that the rejection above stays visible next to it.
