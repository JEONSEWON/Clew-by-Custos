# Live Alert Labelling: Results

Measurement against the predictions in
[`LIVE_FAILURE_ALERT_LABELLING_AMENDMENT_PREREG.md`](LIVE_FAILURE_ALERT_LABELLING_AMENDMENT_PREREG.md)
§5, which its §6 requires be published whether it passes or not. Measured
2026-09-01. Rubric and labels were committed before this number existed.

**Headline: the gate passes at 0.7500 and must not be used. P6 rejects, and
the split says why: precision is 1.0000 on read-like tools and 0.0000 on shell
commands, and the pooled figure is carried by a generated corpus that is almost
entirely reads. On real sessions it is 4 of 11.**

| # | Prediction | Result |
|---|---|---|
| **P1** | Corpus D yields fewer than 10 pairs | **REJECTED** · 82 · see §1 |
| **P2** | Corpus A yields at least 20 pairs | **PASS** · 34 |
| **P3** | pooled pool reaches at least 40 | **PASS** · 136 |
| **P4** | signal precision ≥ 0.70 | **PASS** · **0.7500** (21/28) |
| **P5** | alert precision within 0.15 of signal | **REJECTED** · 1.0000 vs 0.7500, gap **0.25** |
| **P6** | no corpus below 0.50 | **REJECTED** · machine **0.2500**, A **0.4286** |

Two of 30 are `null` and dropped from precision: a `vercel --prod` run twice
through `tail -6`, and a `Write` of identical content to a generated file.
Both are recorded with the reason.

## 1. P1: the reasoning was right and the prediction was arithmetic

Predicted fewer than 10 pairs from Corpus D; measured **82**. Rejected, and not
narrowly.

The reasoning behind it was about *rate*: short sessions repeat less, because
the first repeat candidate appears at a median of 98 tool calls and D's
sessions are far shorter. **That reasoning holds.**

| corpus | sessions with a confirmed pair | rate | pairs |
|---|---|---|---|
| A · trace-commons | 10 / 28 | **35.7%** | 34 |
| this machine | 6 / 87 | 6.9% | 20 |
| D · mimo-cc-1k | 29 / 1,017 | **2.9%** | 82 |

D has the lowest rate of the three, exactly as argued. It also has 1,017
sessions. **The prediction was written as a count while the reasoning was about
a rate**, and 2.9% of a thousand sessions is not fewer than ten.

## 2. P4 passes and the number should not be used

0.7500 clears the 0.70 gate. §6 says a P6 miss means *"the pooled number is not
reportable as one figure. Report the split and do not open delivery on the
pooled value."* P6 misses, so that is what happens.

| source | precision | decidable pairs |
|---|---|---|
| D · generated | **1.0000** | 17 |
| A · real Claude Code | **0.4286** | 7 |
| this machine · real | **0.2500** | 4 |
| **real sessions pooled** | **0.3636** | **11** |

**17 of 28 decidable pairs come from the generated corpus, and every one of
them is correct.** Remove it and the axis is right about 4 findings in 11.

## 3. Why, and it is not about corpora

The split is by **tool**, and it is total:

| tool group | precision | n |
|---|---|---|
| read-like (`Read`, `Glob`) | **1.0000** | 21 |
| shell (`Bash`, `PowerShell`) | **0.0000** | 7 |

Not a tendency. Twenty-one out of twenty-one, and zero out of seven.

**Reading the same file twice with nothing writing to it in between is waste**,
and every such pair in the sample was labelled so.

**Running the same command twice is usually not**, and the reasons are the ones
the rubric named before any label was assigned:

- `Stop-Process` on whatever holds port 3100, guarded by `if ($c)`. It prints
  `stopped` whether or not anything was listening. The identical output *is*
  the command working. Three pairs.
- `make 2>&1` and a `clang` build line, re-run after dozens of calls of
  editing. A rebuild is a check on the work since the last one, and identical
  output means nothing broke — which is the information the agent wanted. Three
  pairs.
- Running the built binary again after 147 calls of work on it. One pair.

The corpus split follows from this, and is not a fact about corpora:

```
D  (generated)  16 Read, 1 Glob,  0 shell   -> 1.0000
A  (real)        3 Read, 4 shell            -> 0.4286
machine (real)   1 Read, 3 shell            -> 0.2500
```

**Generated agent traces read files. Real work also runs commands.** A precision
measured mostly on the first says little about the second, which is what §4 of
the amendment warned about and why per-corpus figures were pre-committed.

## 4. P5: the first pair is not representative, in the good direction

Alert precision — the pair the watcher would actually fire on — is **1.0000**
(9 of 9) against a signal precision of 0.7500. The gap is 0.25 against a
pre-registered bound of 0.15, so P5 is rejected.

It is rejected in the direction nobody worries about: the finding a user would
receive was right every time in this sample. But n is 9, all the misses sit in
non-first pairs, and a gap this size means the two numbers are not
interchangeable — which is exactly what P5 was written to detect. It is not
evidence that alerting is safe.

## 5. What this does and does not license

**Does not:** open delivery. §6 is explicit, and the pooled figure that clears
the gate is carried by a corpus whose tool mix does not look like real work.

**Does:** name a repair that is measurable rather than a hope. The axis is
precise where the target is a read and imprecise where it is a command. A live
trigger restricted to read-like tools would have been right on 21 of 21 here.

That restriction is **not made in this document.** It is a change to §3.2's
trigger, chosen after seeing which slice scored well, and taking it without a
pre-registration is the move the whole rule-8 route exists to prevent. It needs
its own document, its own predictions, and labels drawn fresh — 21 of 21 on
pairs selected by a rule written after the fact is not a measurement.

## 6. What is not claimed

- **No false-positive rate for the live path.** These are pairs from batch
  analysis of finished sessions. The watcher confirms the same pairs with the
  same function, but it has never been labelled on findings it produced itself.
- **One labeller, one pass.** No second annotator and no agreement statistic.
  MAST's own human study reported κ = 0.88; there is no equivalent here.
- **28 decidable pairs**, 11 of them from real sessions. Every figure in §2 and
  §3 rests on that.
- **Nothing about `context_resend`**, which is 99.76% of measured waste and has
  no live path.
- **The two `null` pairs are not counted either way**, and if both were waste
  the pooled figure would be 0.7667 rather than 0.7500. Neither number changes
  what §2 concludes.
