# Per-Detector Absolute Cost in the JSON Report (Amendment)

Amends `WASTE_RATE_METRIC_PREREG.md` §6.1 (the `waste_rate` report block).
Written 2026-09-02.

---

## 0. A detector that cannot appear on a dashboard

`waste_rate.per_detector` is serialized as three keys per detector
(`src/clew/report/json_report.py:174-179`):

```python
"per_detector": {
    d: {"wr_char": ..., "wr_cost": ..., "waste_bytes": ...}
    for d in DETECTOR_ORDER
}
```

`PerDetectorMetric` carries a fourth, `waste_cost`, and it is **computed and
then dropped**. Only the ratio survives.

That drop propagates. The storage layer builds its per-detector rows from
`cost_summary.detector_breakdown` (`boxdawn-cloud/app.py:_detector_rows`), and
that breakdown is assembled from four `if x is not None` arms — cascade,
context_resend, redundant_read, llm_judge — with **no arm for
`duplicate_creation`**. So no row is written for it, `run_detector.waste_cost`
is `not null` and cannot take one, and the code comment there already says the
consequence: *"the dashboard cannot show it at all… The fix belongs upstream."*

This document is that upstream fix.

## 1. Measured, before deciding (2026-09-02)

Two things were checked so this is not written on a guess:

| | |
|---|---|
| `duplicate_creation.waste_cost` on 15 Claude Code traces | **0.0 on all 15** |
| `repeat.waste_cost` and `redundant_read.waste_cost` on the same 15 | **also 0.0 on all 15** |
| `rollup_hourly_detector` after 0023 | `detectors_seen` = `context_resend`, `provable_duplicate`, `redundant_read` — **three, not four** |

★ The second row matters more than the first. **Tool-side cost is structurally
zero on Claude Code traces** — tool spans carry `token_count=None` and
`cost_rate=None` — so `duplicate_creation` is not a special case. What this
amendment buys is not a larger number. It is that a **measured zero** stops
being indistinguishable from **nothing stored**.

The web layer already renders all four names and prints
`no row recorded for this run` for the missing one, so nothing on screen is
false today. The change replaces that hedge with `$0.00`, which is a different
and better statement: *we looked, and it was zero.*

## 2. What changes

**One key per detector in the JSON.** `waste_cost`, taken from the metric that
already computed it — never recomputed here, because a second computation is a
second answer.

```python
"per_detector": {
    d: {"wr_char": ..., "wr_cost": ..., "waste_bytes": ...,
        "waste_cost": wr.per_detector[d].waste_cost}
    for d in DETECTOR_ORDER
}
```

## 3. What explicitly does NOT change

- **The markdown report.** It does not render `per_detector` at all (checked:
  zero references), so it cannot move.
- **`cost_summary.detector_breakdown`.** Adding `duplicate_creation` there
  would change what the aggregate's `waste_cost` sums, and that is a
  measurement. The breakdown stays four-armed; the new field is read from
  `waste_rate` instead.
- **Every ratio.** `wr_char`, `wr_cost`, `union_*`, `excluded_reason` — all
  unchanged, all still computed the same way.
- **Every detector, every threshold, every stored figure.**
- **The storage layer.** `boxdawn-cloud` sourcing its row from this field is a
  separate change in a separate repository, with its own tests. §8 sequences it.
  **This amendment alone does not make a dashboard show four detectors.**

## 4. The frozen manifest, and how it is handled

Adding a JSON key changes report bytes, and
`tests/test_build_set_regression.py::test_seed42_manifest_sha_matches_frozen`
is already `xfail` for the same reason (an additive `Span.output_is_absent`
field, `CASCADE_ABSENCE_SENTINEL_AMENDMENT_PREREG §7.5`).

**The guard is not deleted and not skipped.** Per the standing rule for
intentional drift:

1. The drift is verified **per trace** to be serialization-only — the same
   report with the new key removed must hash to the pre-change value.
2. The `xfail` stays **strict**, and its `reason` names this amendment
   alongside the existing one, so the manifest cannot silently drift for a
   third reason nobody wrote down.

## 5. Predictions

| # | Prediction | What rejects it |
|---|---|---|
| **P1** | all four detectors in `per_detector` carry `waste_cost` | any missing |
| **P2** | each value equals `wr.per_detector[d].waste_cost` exactly — read, not recomputed | any difference |
| **P3** | every other key in the JSON is unchanged, including all three existing per-detector keys and `excluded_reason` | any change |
| **P4** | the **markdown** report is byte-identical after normalising the `analyzed` stamp, on 12 real traces | any difference |
| **P5** | `duplicate_creation.waste_cost` is `0.0` on the 15 traces measured in §1, reproducing that measurement | any non-zero, which would mean §1 measured something else |
| **P6** | the manifest drift is serialization-only: removing the new key restores the pre-change hash on every frozen artifact | any artifact differing for another reason |

★ P4 says "after normalising the stamp" because the report carries its own
analysis time, so literal byte-identity is unachievable for any change
including a no-op — measured 2026-09-02, and two earlier preregs said
"byte-identical" and had to be answered as rejected-on-the-letter.

## 6. What would make this fail

- **P2 misses**: stop. A recomputed cost is a second source of truth for a
  number the report already has, which is the defect class this project has hit
  four times in two days.
- **P3 or P4 misses**: stop. An additive field that moves something else is not
  additive.
- **P6 misses**: stop and revert. A manifest that drifts for an unnamed reason
  is a frozen set that is not frozen.
- **P1 or P5 misses**: incomplete, not unsafe. Fix and re-measure.

## 7. What this does not fix

**No number gets bigger.** Tool-side cost is structurally zero on Claude Code
traces, so on the corpus we actually serve every one of these values is `0.0`.
The change is about the difference between *zero* and *absent*, and nothing
more.

`cost_summary.tiers_complete` was considered in the same round and **deferred**:
on 28 Claude Code traces the tiers were complete on all 28 and no other
downgrade path fired, so the field would have equalled `accuracy_flag`
everywhere it could be measured. Non-Claude-Code adapters could not be measured
— the OpenInference dumps need an envelope shim — so whether it differs there
is an open question, not a finding.

## 8. Order of work

1. This document, merged, before any code.
2. The serializer key plus tests. P1–P6 measured, published whether they pass
   or not.
3. **Then** `boxdawn-cloud`: `_detector_rows` sources `duplicate_creation` from
   `waste_rate.per_detector` instead of the breakdown, with its own tests. Only
   after that does `rollup_hourly_detector` carry four detectors.
4. The web layer's `no row recorded` hedge can then be replaced — its decision,
   its timing.
