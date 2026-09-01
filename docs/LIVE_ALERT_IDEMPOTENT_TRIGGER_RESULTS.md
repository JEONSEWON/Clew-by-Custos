# Idempotent-Only Trigger: Results

Measurement against the predictions in
[`LIVE_ALERT_IDEMPOTENT_TRIGGER_PREREG.md`](LIVE_ALERT_IDEMPOTENT_TRIGGER_PREREG.md)
§6, which its §7 requires be published whether it passes or not. Measured
2026-09-01. Labels were committed before this number existed, on pairs
disjoint from the sample that suggested the restriction.

**Headline: the gate passes at 0.9667 against a raised bar of 0.85, and P4 —
the check that made the last pooled figure unusable — passes on every source
including the real ones. P3 is rejected, and it was arithmetically impossible
as written.**

| # | Prediction | Result |
|---|---|---|
| **P1** | at least 30 unlabelled idempotent pairs | **PASS** · 65 |
| **P2** | precision ≥ 0.85 | **PASS** · **0.9667** (29/30) |
| **P3** | at least 15 of 28 Corpus A sessions still alert | **REJECTED** · 8 · see §2 |
| **P4** | no source below 0.70 | **PASS** · A **0.8333**, D 1.0000, machine 1.0000 |
| **P5** | every stored figure bit-identical | **PASS** |

No pair was undecidable this round.

## 1. P4 is the result, not P2

Last time the pooled figure cleared its gate and could not be used, because
Corpus D carried it: 1.0000 on generated traces against 0.2500 and 0.4286 on
real ones. §5 of this pre-registration counted the pool *before* drawing and
said so plainly — 57 of 65 candidates from D, at most 8 from real sessions —
and named P4 as the prediction that mattered.

It holds:

| source | precision | pairs |
|---|---|---|
| this machine · real | **1.0000** | 2 |
| Corpus A · real | **0.8333** | 6 |
| Corpus D · generated | **1.0000** | 22 |
| **real sessions pooled** | **0.8750** | **8** |

Real sessions score 0.8750, above both the 0.70 floor and the 0.85 gate. The
class is uniform across corpora in a way the unrestricted trigger was not.

⚠️ **Eight real pairs.** That is what the corpora contain and it is a thin
basis for a figure this clean. The Clopper-Pearson 95% two-sided interval on
7 of 8 is **[0.4735, 0.9968]**; the lower bound sits below the 0.70 floor,
let alone the 0.85 gate. The point
estimate passes and the interval does not settle it.

## 2. P3: rejected, and the number was never reachable

Predicted at least 15 of 28 Corpus A sessions would still alert. Measured
**8**.

The prediction is impossible as written. **Only 10 of the 28 sessions produced
any confirmed pair at all**, before any restriction. Fifteen was never
available, and the sentence was written without checking the base.

What was actually measured:

```
Corpus A, 28 sessions
  alerting before the restriction : 10
  alerting after                  :  8      (80% retained)
```

The restriction silences 2 sessions of 10. That is what P3 was trying to check
— whether narrowing the trigger empties the feature — and 80% retention is a
good answer to it. **The prediction is still reported as rejected**, because it
is, and because this is the second arithmetic error of the same kind in two
documents: the labelling amendment's P1 predicted a count from reasoning about
a rate, and this predicted a count without checking the population it was drawn
from. Both were arithmetic, not judgement, and both are on the record.

## 3. The one `false`, and why it is the interesting label

[8] re-reads `index.html` after **four `Edit` calls to that same file**, and
the bytes came back identical.

Rubric 3a: re-reading after editing is a check, and the agent could not know in
advance what would come back. Labelled not-wasted.

It came back identical because the reads take the head of the file while the
edits landed further down. **That is the case the identical-output gate cannot
see on its own** — and it is the reason the rubric asks what happened between
the two calls rather than trusting the gate. The restriction does not fix this;
`Read` is idempotent and this pair is exactly the kind that survives it.

One in thirty here. It is the residual false-positive shape of this axis, and
it is named rather than rounded away.

## 4. What is not claimed

- **Delivery does not open.** §8 step 5 of the pre-registration keeps that a
  separate decision, and the eight-real-pair interval in §1 is the reason not
  to treat 0.9667 as settled.
- **No false-positive rate for the live path.** These are pairs from batch
  analysis of finished sessions. The watcher confirms the same pairs with the
  same function and has still never been labelled on findings it produced
  itself.
- **One labeller, one pass.** No second annotator, no agreement statistic.
- **A class of real waste no longer alerts.** A genuinely pointless repeated
  build is waste and this will never mention it. §4 of the pre-registration
  said so before the measurement and it is still true after.
- **Nothing about `context_resend`**, which is 99.76% of measured waste and has
  no live path.
