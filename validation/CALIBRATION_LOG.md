## calibration @ 2026-06-07T09:31:05.433005+00:00

- model: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`
- revision: `e8f8c211226b894fcb81acc59f3b34ba3efd5f42`
- chosen φ: **0.514345**
- chosen N: **2**

### separation

- gap (P10 dup − P90 prog): **0.220847**  (must be > 0)
- Cohen's d: **4.3803**  (must be ≥ 0.5)
- pair-level dev_fpr_estimate (share of progression pairs with cos ≥ φ): **0.0**  (must be ≤ 0.15)
- trace-level cascade FPR (C4, reporting only): **0.0**  (pre-registered target ≤ 0.10)

### cosine distributions on dev set

| distribution | count | P10 | median | P90 | mean |
|---|---|---|---|---|---|
| duplicate (dup)  | 50  | 0.624768  | 0.833652  | 1.0  | 0.816025  |
| progression (prog) | 40 | 0.338028 | 0.362569 | 0.403921 | 0.366772 |

φ is pinned to the midpoint between P10(dup) and P90(prog); if the two
distributions separate cleanly at P10/P90 then dev_fpr_estimate ≈ 0 should hold.

