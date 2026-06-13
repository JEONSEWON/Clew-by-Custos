## calibration @ 2026-06-07T09:31:05.433005+00:00

- model: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`
- revision: `e8f8c211226b894fcb81acc59f3b34ba3efd5f42`
- chosen φ: **0.514345**
- chosen N: **2**

### separation

- gap (P10 dup − P90 prog): **0.220847**  (must be > 0)
- Cohen's d: **4.3803**  (must be ≥ 0.5)
- pair-level dev_fpr_estimate (진전 쌍 중 cos ≥ φ 비율): **0.0**  (must be ≤ 0.15)
- trace-level cascade FPR (C4, 보고만): **0.0**  (사전등록 목표 ≤ 0.10)

### cosine distributions on dev set

| 분포 | count | P10 | median | P90 | mean |
|---|---|---|---|---|---|
| 중복(dup)  | 50  | 0.624768  | 0.833652  | 1.0  | 0.816025  |
| 진전(prog) | 40 | 0.338028 | 0.362569 | 0.403921 | 0.366772 |

φ 는 P10(중복)과 P90(진전) 의 중점에 박혀, 두 분포가 P10/P90 으로 깨끗이 갈리면 dev_fpr_estimate ≈ 0 이 되어야 한다.

