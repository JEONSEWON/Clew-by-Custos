# Live Alert, Idempotent-Only Trigger (Pre-registration)

**Status.** Amends the trigger frozen in
[`LIVE_FAILURE_ALERT_PREREG.md`](LIVE_FAILURE_ALERT_PREREG.md) §3.2, after
[`LIVE_FAILURE_ALERT_LABELLING_RESULTS.md`](LIVE_FAILURE_ALERT_LABELLING_RESULTS.md)
rejected P6. Per `feedback_rule_8` this is pushed before the code. §2, §4, §6
and §7 are frozen positions. **Nothing here is measured on the 30 pairs already
labelled** — §5 says why that matters and what is used instead.

---

## 0. What the labelling found

30 pairs, 28 decidable, hand-labelled against a rubric committed first. Pooled
precision **0.7500**, which clears the 0.70 gate and is not usable, because the
per-corpus figures rejected P6: **0.2500** on this machine, **0.4286** on
Corpus A, **1.0000** on the generated Corpus D.

The cause is not the corpora. It is the tool, and the split is total:

| | precision | n |
|---|---|---|
| `Read`, `Glob` | **1.0000** | 21 |
| `Bash`, `PowerShell` | **0.0000** | 7 |

Reading a file twice with nothing writing to it in between was waste in every
instance. Running a command twice was waste in none, for reasons the rubric
named before any label existed: `Stop-Process` guarded by `if ($c)` prints
`stopped` whether or not anything was listening, and `make` re-run after thirty
calls of editing is a check whose identical output is the information.

Corpus D scores 1.0000 because it is 16 reads and one glob with no shell at
all. **Generated agent traces read files; real work also runs commands.**

## 1. Why this is a real distinction and not a slice that scored well

Choosing a subset after seeing which one scored is the move rule 8 exists to
prevent, and §5 of the results document refused to make it there. What makes it
defensible here is that **the subset was already defined, frozen, and shipped,
before any of this was measured.**

`clew.config.builtin_tools()` classifies every known tool into four categories
(`docs/CLEW_YAML_PHASE1`, live since 2026-07). One of them is `idempotent`:
tools whose call cannot change the world. `Read`, `Glob`, `Grep`, `LS`,
`github-get_file_contents`, `notion-API-get-page`, and about a hundred others.
`Bash` and `PowerShell` are in `bw_blackbox` and `side_effect`, never in
`idempotent`.

Checked against the labels: **the existing category and the observed boundary
agree on all 28 decidable pairs**, with no exceptions in either direction. The
boundary was not drawn to fit the result; it was already there.

**The mechanism is why.** For an idempotent call, "same input, nothing wrote to
the target, same output" leaves no room for the second call to have been
informative. For a shell command, an identical output can be the command
succeeding at what it does — that is what idempotent housekeeping looks like
from outside — and the trace cannot tell the two apart.

## 2. The change

**The live trigger fires only on pairs whose tool is in the `idempotent`
category.** One line in the watcher's confirmation step.

Everything else in §3.2 stands: one alert per session on the first confirmed
pair, one per `(session, signal)` ever, at most three per project per hour, and
nothing when the session has already ended.

**`clew.yaml` follows.** A user who reclassifies a tool changes what alerts
them, because that file is already the place where a user's own tools are
declared. A user who marks their deploy script `idempotent` will get alerts
about it, which is the correct consequence of the declaration they made.

## 3. What is explicitly NOT changed

- **The batch path.** `cascade`, the waste rates, `waste_span_count`, every
  stored figure and every published number are computed over all tools exactly
  as before. This narrows *what interrupts a person*, not *what is measured*.
- **The report.** A repeated `Bash` call still appears in the analysis and in
  the issue list. It stops being a reason to send mail.
- **φ, N, `confirm_pair`, the earliest-pair rule, the caps.**
- **Shadow mode.** Delivery is still closed and this document does not open it.
  §7 of the original prereg makes P3 the gate, and this re-measures it.

## 4. What this costs

**Fewer alerts.** On the pool, 7 of 28 decidable pairs were shell; those
sessions now produce nothing. Whether a session alerts at all depends on
whether its *first* confirmed pair is idempotent, and that number is not known
in advance — §6 P3 measures it and P4 bounds how far it may fall.

**And a class of real waste stops alerting.** A genuinely pointless repeated
build is waste, and this will not mention it. That is the trade: the axis
cannot tell that case from the seven in the sample, so it says nothing about
any of them rather than being wrong about most.

## 5. The sample must be fresh, and here is the rule for it

The 21 of 21 in §0 is **not evidence for this document**. Those pairs were
selected by a sample drawn before the restriction existed, and scoring the
restriction on them is scoring a rule on the data that suggested it.

**A new sample of 30 idempotent pairs**, drawn from the same pool of 136 with
`random.Random(20260903)`, stratified by source, **excluding every pair already
labelled**. The pool holds 21 labelled idempotent pairs, so the new draw comes
from the remainder.

If fewer than 30 unlabelled idempotent pairs exist, the sample is every one of
them and the count is reported rather than topped up.

**★ The pool is counted here, before the draw, because its shape is a known
weakness of this measurement rather than something to discover afterwards.**
136 pairs, 86 idempotent, 65 of those unlabelled — and they are distributed
**57 from Corpus D, 6 from Corpus A, 2 from this machine**. Real sessions can
supply at most 8 of the 30.

That is the same imbalance that made the last pooled figure unusable, and it
cannot be fixed by sampling: the real corpora do not contain more idempotent
pairs than they contain. Stratification will take every one of the 8 and fill
the rest from D, so **P4 is the prediction that matters most in this document**
— with 8 real pairs against 22 generated ones, a pooled number that passes
while the real slice fails would repeat the last result exactly.

If P4 misses, the honest conclusion is that this axis cannot be validated on
the corpora available, and the gate waits for live shadow findings however long
that takes. That outcome is worth reaching cleanly rather than papering over.

Labels committed before precision, in their own commit, as before.

## 6. Predictions

| # | Prediction | What rejects it |
|---|---|---|
| **P1** | the pool holds **at least 30** unlabelled idempotent pairs | fewer — then the sample is smaller and §5's floor applies |
| **P2** | **precision ≥ 0.85** on the fresh sample | below 0.85. Deliberately above the 0.70 gate: §0 measured 1.0000 on this class, and a restriction justified by that should be held to more than the number it was carved out of |
| **P3** | **at least 15 of 28** Corpus A sessions that would have alerted still alert — the restriction does not silence most sessions | fewer than 15 |
| **P4** | no source's precision is below **0.70** | any below it, which would mean the class is not uniform across corpora after all |
| **P5** | every stored figure and every corpus aggregate is **bit-identical** | any change |

P2 is the gate. P4 is the one that repeats the check P6 failed last time, at a
higher floor, and it is the reason this is worth doing rather than assuming.

## 7. What would make this fail

- **P2 misses**: the axis stays in shadow permanently and the measured
  false-positive rate is published. It does not ship at a lower gate; that is
  what the 0.70 originally was, and this document raised it on purpose.
- **P4 misses**: same as last time — the pooled number is not reportable and
  delivery does not open on it.
- **P5 misses**: immediate stop. A trigger change reached a measurement.
- **P1 misses**: not a stop. The sample is smaller, the interval is wider, and
  both are reported.
- **P3 misses**: not a stop either, but it is the number that decides whether
  this is a feature or a technicality. An axis that alerts on almost nothing is
  not a safe axis, it is an absent one, and that should be said plainly.

## 8. Order of work

1. This document, merged, before any code.
2. The one-line restriction in the watcher, with tests.
3. Draw the fresh sample. P1 measured. Labels committed before anything is
   computed.
4. P2, P3, P4, P5 measured and published whether they pass or not.
5. Opening delivery remains a separate decision after that, unchanged.
