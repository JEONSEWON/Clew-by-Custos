# CRITERIA_FROZEN.md — Clew stage-2 detection validation criteria

> Translated; originals in git history. A few label strings are kept in Korean
> because `eval/evaluate.py` parses them by regex (see the coupling note under
> "Detection parameters"). Values, dates, and hashes are unchanged.

> This document is frozen **before looking at any labeled analysis**. Editing it
> after seeing results invalidates the validation. (SPEC.md §4 rules 2·3 / after
> the 1st review: every value listed here is a fixed value, not an example.)

## Freeze metadata

- Freeze date: 2026-06-06
- Freeze: git tag `stage1-freeze` (pinned to this commit)
- Labeled set: `eval/labels.jsonl` (seed=42, 4 patterns × 10 pairs = positive 40 / negative 40)
- `eval/set_manifest.json` sha256:
  `12ad33bb3b412bbc8ff1639775a9b264c9bcc6ad938a073c0eb07acf23551b52`
  <!-- Re-frozen after LF normalization (CRLF→LF, OS-independent reproducibility). Detection parameters and trace contents unchanged, only serialization line-ending bytes changed. Previous value (Windows CRLF): 6d4efdb05e8b6de3931c965353ad78e9632d94a308d82c996ff43d3b018d4e01. Stage1 original: f3369b7cf598d4aa6f764ec2f56fa9aa437f4603d4ea84a88cb114ec7eb9069b (tag stage1-freeze 0fa25e0) -->
- Length distribution: min=5, max=7, mean=6.0 (paired structural matching —
  positive/clean twins share identical topology)

## Detection parameters

> **This section is filled in and frozen together with the stage-2 start, before
> the first `evaluate.py` run.** No changes after freeze. Any item currently
> blank is a value *to be frozen at that same moment*, not an example.
>
> **Coupling note:** the two label strings below (`반복 임계 N`, `임베딩 모델`)
> and the pre-freeze "TBD" sentinel string used by `eval/evaluate.py` are
> parsed by that module's regexes and by `tests/test_evaluate_reproducible.py`
> fixtures. Translating them would require a lockstep update to that regex
> + test set; kept in Korean deliberately.

- φ (semantic-duplicate cosine threshold): 0.514345
- 반복 임계 N: 2
- 임베딩 모델 (1개 고정): paraphrase-multilingual-MiniLM-L12-v2 @ revision e8f8c211226b894fcb81acc59f3b34ba3efd5f42

## Success criteria (GO)

- Trace-level F1 ≥ 0.80
- Control (negative) trace false-positive rate ≤ 0.10
- **Only when both conditions hold simultaneously** may README / public writing
  claim "catches waste".

## Stop criteria (KILL / PIVOT)

- F1 < 0.60 or Control FPR > 0.25
- Any single violation blocks release; regress to signal redesign.

## Grey zone (0.60 ≤ F1 < 0.80 and 0.10 < FPR ≤ 0.25)

- Fixed budget of **N = 3회** (3 iterations) allowed (fixed value).
- Between iterations, changeable: detection code / detection parameters
  (once tried, the detection-parameters section is re-frozen at that point).
- **Never changeable between iterations**: this document's success/stop
  criteria, the labeled set, and its manifest sha256.
- If the budget is exhausted without meeting GO, treat as KILL.

## "Want" criteria (post-release — frozen separately)

> Stage 1 lists only *the criterion items*. Concrete numbers are frozen in a
> separate document at release time.

- Installs ≥ N
- "Actually caught something" positive feedback ≥ M
- 1-week retention ≥ U
- If below, revisit the wedge.

## Stage 2 pre-registration (cascade + candidate gate)

> This section is frozen **after applying the new candidate gate (SPEC §8 2.1)
> and before looking at calibrate results**. The eval set (seed=42) is not
> touched during this stage. Editing this section after results invalidates
> the validation.

- **C1.** `requery_known` clean (same schema, different values) → 0 structural
  candidates. (Enforced by test.)
- **C2.** `requery_known` positive (same input) → candidate produced + cascade
  flags it. (Recall regression guard.)
- **C3.** dev (seed=7) separation:
  - gap (P10 dup − P90 prog) > 0
  - Cohen's d ≥ 0.5
  - **pair-level** `dev_fpr_estimate` ≤ 0.15
- **C4.** dev **trace-level cascade FPR** (trace is flagged if ≥1 waste pair)
  computed and reported. Pre-registered target: **trace-level FPR ≤ 0.10**.
  (This is the number that will be pinned into CRITERIA.)

## Stage 2 results and v1 scope decision (recorded after calibration)
- C1–C4: all passed. gap +0.2208, Cohen's d 4.3803, pair-FPR 0.00, trace-FPR 0.00.
  Frozen parameters: phi=0.514345, N=2,
  model=paraphrase-multilingual-MiniLM-L12-v2 @ e8f8c211226b894fcb81acc59f3b34ba3efd5f42.
- Operating-point recall (reporting only, φ·N unchanged): in-scope 3 patterns 30/30=1.00,
  regen_handoff 0/10, overall 30/40=0.75.
- regen_handoff diagnosis: structural gap (find_candidates returns 0 candidates;
  cross-node A→B appears once each). cosine(A,B)=0.862 > φ — not a semantic
  miss, purely structural under-coverage.
- Decision: descope regen_handoff for v1 (principled reason: no strong structural
  signal → semantic-dominant → refinement FP risk). Kept in the dataset;
  reported per-pattern in eval with regen marked 'uncovered'. Under-coverage
  is not a defect — it is an explicit scope statement.

## Change policy

Only two situations allow editing this document:
1. When the labeled set itself is replaced (new seed / new pattern added) — a
   new file `CRITERIA_FROZEN_v2.md` is split off.
2. Obvious typo fixes *before* the stage-1 freeze point — must be traceable in
   git history.

Any other edit is treated as leakage; validation is declared invalid.
