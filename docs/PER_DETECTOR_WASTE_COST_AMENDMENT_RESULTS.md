# Per-Detector Absolute Cost — Results

Measurement against the predictions in
[`PER_DETECTOR_WASTE_COST_AMENDMENT_PREREG.md`](PER_DETECTOR_WASTE_COST_AMENDMENT_PREREG.md)
§5, which its §6 requires be published whether it passes or not. Measured
2026-09-02, the same day the amendment merged.

**Headline: P1–P5 pass. P6 is not applicable and its premise was wrong — the
frozen manifest hashes serialized `Trace` objects, not reports, so this change
cannot drift it. The prediction was written about the wrong artifact.**

| # | Prediction | Result |
|---|---|---|
| **P1** | all four detectors carry `waste_cost` | **PASS** · 12 of 12 real traces |
| **P2** | read from the metric, not recomputed | **PASS** · four distinct values round-trip exactly |
| **P3** | every other JSON key unchanged | **PASS** · 12 of 12, identical once the new key is removed |
| **P4** | markdown byte-identical (stamp normalised) | **PASS** · 12 of 12 |
| **P5** | `duplicate_creation.waste_cost` reproduces 0.0 | **PASS** · 0.0 on every trace measured |
| **P6** | manifest drift is serialization-only | **N/A** · see §3 |

994 tests, 1 xfailed, ruff clean (was 987).

## 1. The field, on a real trace

```json
"per_detector": {
  "repeat":             {"wr_char": 0.0,      "wr_cost": null, "waste_bytes": 0,   "waste_cost": 0.0},
  "context_resend":     {"wr_char": 0.012415, "wr_cost": null, "waste_bytes": 124, "waste_cost": 0.00057018},
  "redundant_read":     {"wr_char": 0.0,      "wr_cost": null, "waste_bytes": 0,   "waste_cost": 0.0},
  "duplicate_creation": {"wr_char": 0.0,      "wr_cost": null, "waste_bytes": 0,   "waste_cost": 0.0}
}
```

★ `context_resend` is **not** zero. §1 of the amendment said tool-side cost is
structurally zero on Claude Code traces, and that is what the three zeros are —
the chunk-based detector is priced from LLM calls and carries a real number.
So the field is not a column of zeros; it is a column in which the tool-side
detectors happen to be zero, for a reason already documented.

## 2. What was measured on real traces, not fixtures (P3, P4)

`_per_detector_cost_bytes.py` renders both the markdown and the JSON twice —
once on the working tree, once with the added line reverted — over 12 traces
from 48 KB to 182 KB.

| | |
|---|---|
| markdown byte-identical | **12 / 12** (moved 0) |
| JSON identical once `waste_cost` is removed | **12 / 12** (differ 0) |
| all four carry the field | **12 / 12** |

The JSON check is the strong form of "additive": rather than diffing key lists,
it deletes the new key from the after-report and requires the result to equal
the before-report exactly. Anything else that moved would survive that deletion
and show up.

The `analyzed` stamp is normalised in both, because the report carries its own
analysis time and literal byte-identity is unachievable for any change,
including a no-op. The amendment said so in advance this time.

## 3. ★ P6 was a prediction about the wrong artifact

The amendment planned for the frozen manifest: adding a JSON key changes report
bytes, `test_seed42_manifest_sha_matches_frozen` is already `xfail`, and §4
described verifying the drift per-trace and extending the xfail reason.

**None of that applies.** The manifest hashes
`eval/generators/build_set.py`'s output, which writes
`trace.model_dump_json()` — **serialized `Trace` objects**. `render_json` is
not in that path at all. The existing xfail is about `Span.output_is_absent`,
which is a field on a `Span` and therefore genuinely in those artifacts.

Confirmed by running it: still `xfail`, same reason string, no unexpected pass
and no new failure. **The xfail was not touched**, and extending its reason
would have attached this amendment to a drift it did not cause.

This is the third prediction in two days whose wording outran the artifact:
"byte-identical" twice (a report that stamps its own time), and now a manifest
guard aimed at a serializer that does not feed it. **The pattern: a prediction
about a guard needs the guard read, not its name recognised.**

## 4. Type stability, found while implementing

`round(0, 8)` returns the **int** `0`. Without a cast, a zero-waste detector
would serialize as `0` and a non-zero one as a float, so a consumer
type-checking the field would read the two differently. The field casts to
`float` first and a test pins it.

⚠️ `union_waste_cost` beside it has the same wobble and is **deliberately left
alone**: changing it would alter an existing key's bytes, which §3 forbids and
P3 measures. Carried as a separate observation, not fixed here.

## 5. What this does not do

**No dashboard shows four detectors yet.** §8 of the amendment sequences it:
the storage layer must source `duplicate_creation` from
`waste_rate.per_detector` instead of from `cost_summary.detector_breakdown`,
which is a change in `boxdawn-cloud` with its own tests. Until then
`rollup_hourly_detector` carries three, as measured after 0023
(`detectors_seen`: `context_resend`, `provable_duplicate`, `redundant_read`).

And the web layer's `no row recorded for this run` hedge is correct until that
lands. Replacing it is that layer's decision and its timing.

## 6. Carried

- `union_waste_cost` serializes as `0` rather than `0.0` on a zero-waste trace.
  Same class as the defect fixed here, one field over, and fixing it moves an
  existing key.
- `cost_summary.tiers_complete`, deferred in the same round with the reason in
  the amendment's §7: on 28 Claude Code traces the tiers were complete on all
  28 and no other downgrade path fired, and the non-Claude-Code case needs an
  OpenInference envelope shim before it can be measured at all.
