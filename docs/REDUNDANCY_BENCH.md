# §24 — RedundancyBench Adapter + F1 Mapping Pre-registration (2026-07-18, Rule 8)

**Target dataset**: RedundancyBench (arXiv:2605.29893, 4open.science/r/RedundancyBench, MIT © 2026 Minyang Hu). tau2-bench 3 domains (airline / retail / telecom) — 200 traces + human step-level redundancy labels.

**Why this benchmark**:
- Toolathlon (§23) only labels success/failure — step-level verification is impossible. We cannot quantitatively compare our waste definition's F1 against the paper.
- RedundancyBench provides **step-level GT** (4 categories: exploratory / duplicated / abnormal / incorrect). The paper's best baseline step-level F1 = 24.88% (Window-to-One). A low ceiling → a precision-first gate is likely to matter.
- No data redistribution (MIT, but `data/` is gitignored, local analysis only). The paper's evaluate.py is reproducible.

**Recon output** (Rule 7 addendum, bundled in the same commit):
- `field_test/diagnostics/recon_redundancybench.py` — schema recon (Q1–Q5)

---

## §24.1 — Data / License

**Source**: `anonymous.4open.science/r/RedundancyBench` (anonymous arxiv review copy, MIT).

**Local path** (do not commit — `.gitignore: data/`):
```
data/redundancy_bench/
├── LICENSE                MIT © 2026 Minyang Hu
├── README.md              6970 bytes
├── LLM_judge/
│   ├── judge.py           (LLM inference — not used)
│   ├── evaluate.py        (evaluation script — our comparison baseline)
│   └── requirements.txt
└── data/domain/
    ├── airline/     annotation.json + final_traces.json
    ├── retail/      annotation.json + final_traces.json
    └── telecom/     annotation.json + final_traces.json
```

**Scale** (recon-measured):

| Domain | sims (final_traces) | annotated tasks | with_red | assistant tool spans | user tool msgs (excluded) |
|---|---:|---:|---:|---:|---:|
| airline | 40 | 40 | 37 | 372 | 0 |
| retail | 48 | 44 (4 extras ignored) | 39 | 409 | 0 |
| telecom | 112 | 112 | 107 | 847 | 1035 |
| **Total** | **200** | **196** | **183** (93.4%) | **1628** | 1035 |

**Typed distribution**:
- exploratory: 8 + 85 + 522 = **615**
- duplicated: 2 + 44 + 84 = **130**   ← direct match for our sha256 gate
- abnormal: 4 + 28 + 68 = **100**
- incorrect: 6 + 20 + 12 = **38**

**GT pair structure**: `redundant_step_idx` in every domain is an adjacent (call_idx, result_idx) pair. `pair_bad=0` (recon Q2 extended verification). Example — airline task=1: `[6,7,10,11,12,13,8,9,16,17,18,19]` sorted → (6,7)(8,9)(10,11)(12,13)(16,17)(18,19). turn 6 = assistant call, 7 = tool result confirmed.

**Exception** (calculation convention noted separately in §24.3):
- 2 telecom tasks have odd-length GT (12 idxs total unpaired). Every unpaired idx has `role=tool, requestor=user` (user-simulated device tool). Our adapter policy does not spanify these → pre-separated as an unpredictable set.

---

## §24.2 — Adapter Mapping (recon-confirmed)

**New module**: `src/clew/ingest/redundancy_bench.py`

**Branch policy** (`_load_trace_auto` extension):
- Not `.jsonl` — RB uses `final_traces.json` (a single JSON `{tasks: [], simulations: []}`).
- New extension function `iter_redundancy_bench_traces(path: Path) -> Iterator[Trace]` yields multiple traces per file. `_load_trace_auto` returns only the first sim (same contract as CC/Toolathlon).
- Branch marker: `tasks` AND `simulations` keys at the top-level dict.

**Span mapping**:

| Span field | RB source | Rationale |
|---|---|---|
| `trace_id` | `simulation.id` (uuid) | recon Q3 |
| `span_id` | `messages[i].tool_calls[j].id` (e.g. `call_be9cc486…`) | recon Q3 (join key, matches the `id` field on the tool message. Not `tool_call_id` — RB is flat) |
| `parent_span_id` | synthetic root (`root-<sim.id>`) | Toolathlon precedent (§23.1) |
| `agent_or_node_id` | `tool_calls[j].name` (RB is flat, no `function:` nesting) | recon Q3 |
| `span_kind` | `"tool"` | all are tool calls |
| `input_text` | `json.dumps(tool_calls[j].arguments, sort_keys=True, ensure_ascii=False)` | RB `arguments` is a dict (not str, unlike Toolathlon). Re-serialization with sort_keys yields a stable sha256 |
| `output_text` | matching tool message `content` (str) | recon Q3 (observed as a flat string) |
| `start_time` / `end_time` | synthetic — `base + turn_idx * seconds` | see §24.2.1 |
| `token_count` | `None` | not provided by RB |
| `model` | not present at trace top-level. If needed, attach via metadata | — |
| `cost_rate` | `None` | — |

**Filter**: tool_calls / tool msgs with `requestor='user'` are **excluded**. Reasons:
- recon-confirmed: telecom 1035, airline/retail = 0.
- These are user-simulated device tool calls, not agent behavior.
- Spanifying them would violate our definition ("agent-repeated calls").

**Trace.metadata extension** (Span structure unchanged, §22.11 precedent):
```python
{
    "source": "redundancy_bench",
    "domain": "airline" | "retail" | "telecom",
    "task_id": simulation["task_id"],
    "sim_id": simulation["id"],
    "reward_info": simulation.get("reward_info"),
    # required to execute §24.3 Convention A: span_id → (call_turn_idx, result_turn_idx)
    "rb_span_to_turn_pair": {span_id: [call_idx, result_idx], ...},
    # user-issued tools recorded separately (ignored in matching calc)
    "rb_user_tool_idx": [turn_idx, ...],
}
```

### §24.2.1 — synthetic timestamp convention

**Fact**: RB `messages[i]` has a `timestamp` field (ISO datetime). There are **no parallel tool_calls** (recon-confirmed: parallel_msgs=0 across all 3 domains).

**Convention**:
- Use the original timestamp (synthetic unnecessary since it exists).
- Fallback on parse failure: `base + turn_idx * 1s` (a reduced form of the Toolathlon precedent).
- No sub_idx needed since there are no parallel calls.

### §24.2.2 — join verification

- No `tool_call_id` field (different field name from Toolathlon). Join key is `tool.id`.
- The id set in assistant.tool_calls == the id set in matching tool msgs (assistant-requestor only).
- Explicit raise on unmatched (§21.4). Recon-confirmed: airline 40/40, retail pending, telecom checked after filtering to assistant-only.

---

## §24.3 — GT Comparison Convention (fixed before seeing results)

**Core decision**: the paper's `evaluate.py:evaluate_standard()` computes step-level F1 as micro-averaged —
```python
tp = |GT_set ∩ Pred_set|
fp = |Pred_set - GT_set|
fn = |GT_set - Pred_set|
precision = tp/(tp+fp);  recall = tp/(tp+fn);  f1 = 2PR/(P+R)
```
Per task, `GT_set` = `set(annotation["redundant_step_idx"])`, `Pred_set` is the set of turn_idxs the detector emits.

**Our span_id → turn_idx correspondence** (recon-confirmed):
- 1 span = 1 tool_call.id = 1 (assistant_call_turn_idx, tool_result_turn_idx) pair.
- 88–91% of cases have gap=1 (the tool result is the turn right after the assistant call). The rest have a user message interleaved (still joined by the same `tool.id`, arbitrary gap).
- However, GT `redundant_step_idx` is **always an adjacent pair** (pair_bad=0). RB annotators always label the assistant call and its result at adjacent idxs.

**Convention A (pair expansion) — selected** ✓
- Each waste span is expanded into two idxs `{call_turn_idx, result_turn_idx}` and inserted into `Pred_set`.
- Example: waste span_id `call_be9cc486…` → lookup `Trace.metadata["rb_span_to_turn_pair"]` → `[2, 3]` → `Pred_set ∪= {2, 3}`.

**Why A**:
- GT is pair-labeled (re-confirmed: pair_bad=0). To put GT and pred on the same unit (single idx), we expand pred to pairs as well.
- Convention B (GT contraction) means bypassing the paper's evaluate.py and redefining evaluation ourselves → cannot compare directly against the paper's 24.88%. Loss of reproducibility.
- Convention C (both) is messy double-reporting. A is primary; B appears only as an appendix-table option.

**Convention A details**:
1. `Pred_set` = ∪ {[call_idx, result_idx] for span_id in waste_span_ids}.
2. `GT_set` = `set(annotation["redundant_step_idx"])` used as-is (no filter/transformation).
3. `tp = |GT_set ∩ Pred_set|` etc., exactly as in the paper.
4. Our adapter's skip set (`rb_user_tool_idx`, 12 idxs of user-issued tool results) is **kept in** `GT_set`. → Marked as unpredictable, this naturally lowers the recall ceiling. Manipulating it (e.g. removing from GT_set) would be dishonest tuning.

**Not-alternatives**:
- The paper's telecom evaluate uses "a dict-keyed method (subtly different by dataset definition)" (recon Q5 quote). We compute all 3 domains uniformly under the airline/retail convention (`evaluate_standard`) — this may differ subtly from the paper's "average" table at this point. Explicit in §24.7 results.

**Convention A predictions**:
- `Pred_set` size = waste_span_count × 2 (no parallelism → each span expands to exactly 2 idxs).
- tp / fp / fn computed at idx granularity (not pair granularity).

---

## §24.4 — Category Scope

**What our gate (structural N=2 → sha256 tool-kind → compact) can catch**:

| RB category | labels | expected hits by our gate | rationale |
|---|---:|---|---|
| duplicated step | 130 | **primary target** | By definition (name, args, output) identical. Direct match to the sha256 gate. |
| abnormal step (error) | 100 | partial hit | Two retries with the same error output → sha256 can match. Different error / new output → miss. |
| exploratory step | 615 | low hits | Diverse args, diverse outputs. Our gate cannot catch these (LLM-judge territory). |
| incorrect step | 38 | very low hits | Off-mission judgment required, outside the gate's scope. |

**Important**: our gate is duplicated-specialized. exploratory (615, 66% of GT) is structurally uncoverable. → step-level recall ceiling ≈ `(130 + partial 100) / 883` ≈ 15–25%.

**Precision-first gate**: our precision is predicted to exceed the paper's baseline (Window-to-One 20% F1). Recall will be low.

---

## §24.5 — Pre-registered Predictions (before seeing results)

**Target**: all annotated sims across 3 domains = 196. Full run of adapter + 3-stage gate (structural N=2 → sha256 → compact).

**Note**: the compact gate is a no-op because RB metadata has no `compact_boundaries` (same as the Toolathlon §23 precedent).

### Predicted numbers

| Metric | Prediction | Rationale |
|---|---:|---|
| assistant tool spans (total) | 1620 – 1640 | recon actual 1628 (assistant-only). ±10 margin for parsing/build exceptions. |
| repeat candidates (structural gate N=2) | 200 – 400 | Toolathlon 108 traces → 177 candidates (5–15%). RB 196 traces × ~1.5% (broader tool set) = 20–50, but the 130 duplicated labels already imply at least 65 repeat pairs. Generous 200–400. |
| sha256 gate survivors | 40 – 120 | 20–30% of candidates (Toolathlon 32/177 = 18%). |
| **final waste (span count)** | **40 – 120** | compact gate is a no-op → same as sha256 survivors. |
| `Pred_set` size (idx unit, pair-expanded) | 80 – 240 | span count × 2 |

### F1 predictions (Convention A basis)

| Metric | Predicted range | Rationale |
|---|---:|---|
| step-level precision | 0.35 – 0.75 | sha256 gate hits duplicated (130 pairs) accurately. Possible false hits on exploratory (recall but legitimate exploration). |
| step-level recall | 0.03 – 0.12 | Of GT 683 pairs, duplicated 65 pairs is the theoretical ceiling. Assuming half of abnormal hits (25 pairs). Actual hits 30–60 pairs → peak recall 60/683 ≈ 8.8%. |
| **step-level F1 (overall)** | **0.05 – 0.20** | Product of the above. At or below the paper's Window-to-One 20% F1. Extreme precision-recall trade-off in absolute terms. |

### Trajectory-level predictions

| Metric | Predicted range | Rationale |
|---|---:|---|
| sims containing waste | 25 – 60 | Toolathlon 14/108 = 13% → RB 196 × 13% = 25. At most 30%. |
| both_red correct | 22 – 55 | Most will fall within with_red=183 traces (assuming no false positives). |
| both_non_red | 8 – 13 | 13 non-red among our no-prediction traces. |
| trajectory-level accuracy | 0.15 – 0.35 | Baseline (predicting has_red for all = 93.4%). We cannot beat the baseline given precision priority. |

### Judgment criteria

**Success definition**:
- Convention A F1 ≥ 0.05 (near or above the paper's lowest baseline One-to-One 8%).
- Precision > 0.35 (primary claim for a duplicated-specialized gate).

**Partial success**:
- F1 0.03–0.05, precision > 0.4 → valid as a precision-oriented gate, complementary to the paper's recall-oriented baseline.

**Failure**:
- F1 < 0.03 or precision < 0.2 → adapter/gate review. Need to analyze why the sha256 gate failed to catch duplicated.

### Stop conditions (§23.5 precedent)

1. Regression on existing 216 tests → stop.
2. Any change to CC / Toolathlon / OTel / OpenInference results → stop. The RB branch must be independent.
3. Any change required to φ / N / model / sha256 logic → immediate stop (re-confirm §22.10 rule).
4. Any Span data structure extension required → immediate stop (only Trace.metadata extension is allowed).
5. Temptation to filter / transform GT `redundant_step_idx` for favorable numbers → **absolutely forbidden**. Execute §24.3 Convention A as-is.

---

## §24.6 — Rule 8 Commit Chain (pre-registration timestamp proof)

This document (§24.1–§24.5) + `field_test/diagnostics/recon_redundancybench.py` = **pre-registration commit**.
- push → server timestamp recorded → Rule 8 satisfied.
- Adapter implementation code (`src/clew/ingest/redundancy_bench.py` + tests + evaluation script) is a **separate commit after push confirmation**.
- Results (§24.7) are an additional commit after execution.
- PR / merge is batched with feat/cc-adapter (separately requested).

**Planned commit files**:
- `docs/REDUNDANCY_BENCH.md` (this document, new)
- `field_test/diagnostics/recon_redundancybench.py` (new, Q1–Q5 recon)

**Do-not-commit files**:
- `data/redundancy_bench/**` — already excluded by `.gitignore: data/`.

---

## §24.7 — Post-execution Results (2026-07-18)

**Run**: `python field_test/eval_redundancy_bench.py`
**Gate**: φ=0.514345, N=2, model=paraphrase-multilingual-MiniLM-L12-v2@e8f8c21, sha256 tool-kind ON.
**Adapter correction** (relative to pre-registration): RB reuses `tool_call.id` within the same sim (airline 20/40, retail 22/48, telecom 45/112 sims). span_id=`f"{tid}#{call_idx}"` makes it unique, and call↔result matching is FIFO. Reflected in the `docs/REDUNDANCY_BENCH.md §24.2` mapping table and in the adapter tests. This correction does not violate Convention A — the turn_pair mapping is still preserved.

**Evaluation**: `import`s `data/redundancy_bench/LLM_judge/evaluate.py` as-is → calls `evaluate_standard` (airline/retail), `evaluate_telecom_one_one` (telecom). No re-implementation.

### Predicted vs actual (Convention A)

| Metric | Predicted (§24.5) | Actual | Verdict |
|---|---:|---:|---|
| assistant tool spans (total) | 1620–1640 | **1628** | ✓ within range |
| waste spans (span count) | 40–120 | **132** | ✗ +12 above |
| step-level precision | 0.35–0.75 | **0.8258** | ✗ above upper bound |
| step-level recall | 0.03–0.12 | **0.1573** | ✗ above upper bound |
| **step-level F1** | 0.05–0.20 | **0.2642** | ✗ **above upper bound** |
| trajectory-level accuracy | 0.15–0.35 | **0.5000** | ✗ above upper bound |

**Without excuses**: 5 of 5 metrics exceeded the upper bound of the pre-registered prediction. This means the pre-registration was too conservative, not that the gate behaved oddly. F1 lands at 26.4%, above the paper's Window-to-One (LLM judge, whole scope) 20%. Precision 0.826 says the precision-first design was more accurate than expected.

### Per-domain breakdown

| Domain | spans | waste | tp | fp | fn | P | R | F1 | traj_acc |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| airline | 372 | 37 | 64 | 10 | 236 | 0.865 | 0.213 | **0.342** | 0.600 |
| retail | 409 | 33 | 42 | 24 | 152 | 0.636 | 0.217 | **0.323** | 0.591 |
| telecom | 847 | 62 | 112 | 12 | 780 | 0.903 | 0.126 | **0.221** | 0.429 |
| **Combined** | **1628** | **132** | **218** | **46** | **1168** | **0.826** | **0.157** | **0.264** | **0.500** |

Telecom recall is low because `role=user`-issued tools remain in GT_set but we cannot predict them (§24.3 explicit policy). Retail precision is comparatively low because most of the 5 false positives are "legitimate re-lookups" (reference-type tools like get_order_details) that sha256 matched.

### §24.4 per-category recall (honest scope for our gate)

| Category | GT count | our hits | recall | Scope |
|---|---:|---:|---:|---|
| **duplicated step** | 130 | **79** | **0.6077** | ← **primary target** |
| abnormal step | 100 | 0 | 0.0000 | Out of scope (error output diversity) |
| exploratory step | 615 | 14 | 0.0228 | Out of scope (LLM-judge territory) |
| incorrect step | 38 | 12 | 0.3158 | Partial hit (likely overlaps with other category labels) |

**Preventing unfair paper comparison (§24.4 principle)**:
- The paper's Window-to-One 20% F1 is measured **over all 4 categories**.
- Our gate is duplicated-specialized. The overall F1 26.4% is near-coincidental — the combination of "accurate detection of duplicated" + "natural suppression of false positives on other categories".
- **Duplicated-only recall 60.77%** is our true performance metric. The abnormal/exploratory recall of 0/2% is expected by design.

### Top false positives (Pred ∈ GT^c) — 5 per domain

**airline** (5 of 10 fp)
1. `task=12 get_user_details` — same user re-lookup. RB treats information re-lookup as a legitimate step (not redundant).
2. `task=31 get_user_details` — same pattern.
3. `task=32 get_reservation_details` — reservation re-lookup.
4. `task=34 search_direct_flight` — same flight re-search.
5. `task=41 get_user_details` — same pattern.

Common cause: two calls of a `get_*` reference tool → sha256 matches. RB annotators do not label the second lookup as redundant when it has a clear purpose. Our gate does not know intent.

**retail** (5 of 24 fp)
1. `task=9 exchange_delivered_order_items` — a successful write is called again (same return). GT exceptionally treats this as not redundant (re-confirmation purpose for exchange).
2. `task=11 get_order_details` — same order re-lookup.
3. `task=22 modify_pending_order_address` — re-lookup after a write op for confirmation.
4. `task=50/53 get_order_details` — same order re-lookup.

**telecom** (5 of 12 fp)
1. `refuel_data` ×3 — refueling twice with the same args, but GT does not label as redundant (2 GB twice = 4 GB, logically a different action). We only look at sha256, so identical output matches.
2. `get_bills_for_customer` — bill re-lookup.
3. `get_details_by_id` — line id re-lookup.

**Real cause of the false positives**: our gate judges "waste if output is fully identical". RB says "not redundant if intent differs". Information re-lookup is a legitimate repeat for state verification. This gap is a structural limit of the sha256 gate. **To push precision higher, we would need a judge that catches the semantic gap (same structure but different intent)** — outside our φ gate's scope.

### Top missed duplicated (GT duplicated ∈ Pred^c) — 5 cases

**retail task=11 turn=14,15**: `reason='Repeat for step 7, 8'` — actual cause per §25 recon (`sha256_mismatch` or an uncharacterized span→pair mapping case). **N=2 is not a window but an occurrence-count threshold** (structural.py:69 `len(occurrences) < n`); cascade has no gap/window argument.

**retail task=58, task=79**: similar cause.

**telecom task=[mobile_data_issue]…turn=29,30**: `reason='Permintaan timeout'` — GT reason itself is "retry after timeout", hence labeled duplicated. The output on the second call may differ (different tool result). sha256 mismatch → miss. Legitimate miss.

**telecom [mobile_data_issue]…turn=10,11**: `reason='This step is not necessary to obtain the business route corresponding to the user's mobile phone number'` — the label rationale is "this step itself is unnecessary", but for us it's a repeat with different args → sha256 mismatch. This type is outside our definition (not a re-call, just a one-off unnecessary call) — the annotator's rationale for tagging it as duplicated is itself subtle.

### Out-of-scope categories (for reference)

- **abnormal step 0/100 hit**: error outputs differ each time (contain timestamps, session ids) → sha256 does not match. A separate error-normalization gate would be needed if desired (post-§25 follow-up).
- **exploratory step 14/615 hit**: by definition exploratory uses different args to explore. What the sha256 gate can catch are only accidental arg repeats. Out of scope.

### evaluate.py verification (pre-registered stop condition 4)

The paper's baseline prediction file (Window-to-One @ 24.88%) is not in the repo (judge.py requires an LLM API call), and we cannot reproduce it locally. Instead:
- We `sys.path.insert` and `import` the original `evaluate.py` → call `evaluate_standard`, `evaluate_telecom_one_one`. No re-implementation.
- Argument/return spec compliance: airline/retail take two `{task_id: set}` dicts, telecom takes `{idx: {'task_id', 'redundant_step_idx'}}` GT + `{idx: set}` pred.

**So there is no suspicion about the computation logic** (their code, as-is). But direct comparison to the paper's 24.88% requires the §24.4 honesty principle above.

### Stop conditions re-confirmed

1. **231 tests pass** (216 → 231, +15 new). Zero regressions. ✓
2. **CC/Toolathlon/OTel results unchanged** (`_load_trace_auto` extension only). ✓
3. **No change to φ / N / model / sha256 logic**. ✓
4. **No Span data structure extension**. Only `Trace.metadata` gains `rb_span_to_turn_pair, rb_user_tool_idx, source, domain, task_id, sim_id, reward_info`. ✓
5. **No GT filtering/transformation**. `annotation.json` is passed to `evaluate.py` as-is. ✓

### Merge policy

- This commit is on the `feat/cc-adapter` branch as the §24 result commit (pre-registration a73ced6 → adapter f193ff5 → this result commit).
- Push only. PR batches §23 (Toolathlon) + §24 (RedundancyBench).

---

## §24.8 — Result Verification (2026-07-18, post-hoc)

Right after the §24.7 push, results exceeded the pre-registered predictions across all 5 axes at the upper bound. 3-step verification (Q1 scope, Q2 metric identity, Q3 prediction-overshoot cause). Diagnostic script: `field_test/diagnostics/verify_rb_eval.py` (Rule 7 addendum, raw only).

### Q1 — scope of F1=0.2642

`evaluate.py` line 32 quote:
```python
gt[tid] = set(item.get('redundant_step_idx', []))
```
`redundant_step_idx` covers all 4 categories combined (exploratory/duplicated/abnormal/incorrect). No type filtering.

**Conclusion**: 0.2642 = **whole scope (4-category union)**. Same scope as the paper's baseline 24.88%. duplicated recall 60.77% is a distinct scope (§24.7.2).

| scope | tp | fp | fn | P | R | F1 |
|---|---:|---:|---:|---:|---:|---:|
| **overall (paper definition, 4 categories)** | 218 | 46 | 1168 | **0.8258** | **0.1573** | **0.2642** |
| duplicated-only strict (fp = pred − dup_gt) | 79 | 185 | 51 | 0.2992 | 0.6077 | 0.4010 |
| duplicated-only inclusive (fp = pred − full_gt) | 79 | 46 | 51 | 0.6320 | 0.6077 | 0.6196 |

### Q2 — evaluate.py identity (pre-registered stop condition 4 re-check)

`field_test/eval_redundancy_bench.py` lines 33-37:
```python
sys.path.insert(0, str(LLM_JUDGE_DIR.resolve()))
import evaluate as ev
```
→ Direct import of RB's original `evaluate.py`. No re-implementation. Function identity itself is guaranteed.

**Caveat 1 (must always accompany)**: `data/redundancy_bench/LLM_judge/` = `['evaluate.py', 'judge.py', 'requirements.txt']` — **no baseline prediction JSON file present**. 24.88% is a cited value from the paper. Not reproduced or verified in our environment. Only the identity of `evaluate.py` function code is guaranteed.

### Q3 — cause of overshooting predictions (deviation log)

| metric | §24.5 prediction | actual (Convention A) | overshoot direction |
|---|---|---:|:---:|
| waste span count | 40 – 120 | 132 | ✗ (+10%) |
| overall F1 | 0.05 – 0.20 | 0.2642 | ✗ (+32%) |
| overall P | 0.35 – 0.75 | 0.8258 | ✗ (+10%) |
| overall R | 0.03 – 0.12 | 0.1573 | ✗ (+31%) |
| trajectory acc | 0.10 – 0.35 | 0.5000 | ✗ (+43%) |

**Caveat 2 (cause of deviation)**: the pre-registered Convention A (pair expansion, `waste_span → {call_idx, result_idx}`) was not carried into the prediction calibration. Recomputing without expansion (call-only):

| pred | tp | fp | fn | P | R | F1 |
|---|---:|---:|---:|---:|---:|---:|
| call-only (no expansion) | 110 | 22 | 1276 | 0.8333 | 0.0794 | **0.1449** |
| pair-expansion (Convention A, canonical) | 218 | 46 | 1168 | 0.8258 | 0.1573 | **0.2642** |

**Expansion adds F1 +0.1193.** call-only F1 0.1449 is **within** the predicted range (0.05–0.20). → At prediction time the confound was: multiplied out `waste span 40–120` but forgot to count the additional result idx. Not a performance/bug issue — a prediction calibration error.

Re-checking whether the recall prediction (0.03–0.12) was confused with duplicated recall (0.6077): no, the overall recall (0.1573) already overshoots the upper bound. Not a scope confusion — a size underestimate.

### Q5 — impact of tid FIFO fix

`e06ae12` (handling tool_call.id reuse): 87/200 sims (43.5%) have tid reuse. Before the fix (raise-on-error state), all such sims would produce pred=∅ → mass fn on duplicated GT.
Exact fix-off F1 requires checking out the pre-adapter commit (not executed; join statistics only).

### Cause of 39% misses (Q4 raw)

All 51 duplicated misses are tagged `in_pair_but_not_wasted` — adapter pairing succeeded, but cascade (φ + sha256 gate) did not judge waste.

**Note**: the description below is an early summary from the §24.7 fold-back time and contains phrasing that mistook N=2 for a "window". For the actual re-analysis see §25 (`recon_N_window.py` Q2). Summary:

- **sha256_mismatch (24/51)**: origin·candidate pair caught, but output hashes differ. e.g. telecom timeout retry (`error → success`). Legitimate by gate definition.
- **sha256_equal_but_not_in_waste (27/51)**: recon script finds origin·candidate pairs whose sha256 matches yet are missing from the cascade waste list. The script's span→pair mapping includes abnormal cases like negative gap (-3) → **uncharacterized, requires separate verification** (§25 Q2 raw for reference).
- Inter-occurrence turn gap distribution: n=51, min=-3, max=30, median=8, p25=3, p75=16. **N is not a window, so gap alone does not block pairing.**

**Summary**: the 39% misses = sha256 gate definition boundary (24) + uncharacterized mapping (27). This section's earlier "outside N=2 window" phrasing was an error; correction is in §25.

### Honesty boundary (§24.8 permitted / forbidden phrasing)

**Permitted**: "RedundancyBench overall F1 0.2642, ahead of the paper's Window-to-One baseline 0.2488. Same `evaluate.py`, deterministic (no LLM), precision 0.8258 / recall 0.1573. **Caveats 1·2 must accompany.**"

**Forbidden**:
- "We reproduced/verified 24.88%" — no baseline prediction file (§24.8 Q2 Caveat 1).
- "We clearly won / dominated" — single benchmark, low recall, and the duplicated-specialized gate may have benefited from scope characteristics (the other 3 categories have recall ≤3%).
- Substituting duplicated recall 60.77% into the overall F1 slot (distinct scope).

---

## §24.9 — False-Positive Deep Dive (fp 46, span-level 22)

`field_test/diagnostics/analyze_rb_fp_46.py` (Rule 7 addendum). fp idx 46 counts idxs after pair expansion; the original waste span count is 22 (most spans have both call+result idxs outside GT).

### fp 22 spans classification

| Classification | Count | Percentage |
|---|---:|---:|
| earlier match exists (same tool_name + input earlier) | 21/22 | 95.5% |
|   of which same input + **same output** (full reproduction) | **21/22** | **95.5%** |
|   same input, different output | 0/22 | 0% |
| no earlier match | 1/22 | 4.5% |
| labeled in another GT category (exploratory/abnormal/incorrect) | **0/22** | **0%** |
| **purely unlabeled** (in no category) | **22/22** | **100%** |
| **human-missed candidates** (same io + unlabeled + 0 state-changing tool calls within window) | **6/22** | **27.3%** |

### Top 5 human-missed candidates (raw)

1. `[airline] task=31 span=…#6 get_user_details` — call_idx=6, earlier @ call=3, output_equal=True, between=0.
   `{"user_id": "daiki_lee_6144"}` → same user details re-lookup. No GT label.
2. `[airline] task=41 span=…#6 get_user_details` — same pattern, `amelia_davis_8890` re-lookup.
3. `[retail] task=79 span=…#24 modify_pending_order_items` — call=24, earlier @ call=22. Same item swap re-executed 2 turns later. No intermediate tool call.
4. `[retail] task=83 span=…#6 find_user_id_by_name_zip` — same name+zip re-search.
5. `[telecom] …#22 refuel_data` — same `{customer_id:C1001, gb_amount:2, line_id:L1002}` re-executed.

### Implication

**Precision 0.8258 may be a lower bound.** All 22 fp spans are outside every one of the 4 GT categories, 21/22 are full reproductions, and 6 have 0 state changes within the window. If they are not in GT = RB annotators missed labeling waste. Clew catches them.

**Caveat (must accompany)**: RB annotations are human reviewer judgments and offer no completeness guarantee. "Unlabeled = annotator miss" is a candidate judgment; owner confirmation required. This section only shows **numbers** (0/22 labeled in other categories, 6/22 candidates with 0 state changes).

**Permitted phrasing**: "Of 22 fp spans, 21 are full reproductions of same input+output, 0 are labeled in other GT categories, and 6 are human-missed candidates with 0 state changes within the window → precision 0.826 may be a lower bound."

**Forbidden**: "All 22 are waste" — state changes outside the window and non-tool context are not inspected, and no owner confirmation yet.

---

## §25 — N=2 Parameter Post-hoc Verification (2026-07-18, post-hoc, roadmap ②)

In the §24.8 fold-back, the phrase "outside N=2 window" appeared. **It was wrong.** This section records `recon_N_window.py` (Rule 7 addendum, raw only), which confirms N's exact meaning and its post-hoc optimality.

### Q1 — Origin and exact meaning of N=2

**Origin**: `validation/CRITERIA_FROZEN.md:23` — "repeat threshold N: 2". **No calibration trace** (grep `N=2` across `src/`, `docs/`; ARCHITECTURE.md states the decision as a fact only, with no derivation procedure). In short, **N=2 is an arbitrary value** (§0 kickoff default), not a derived one.

**Exact meaning** (`src/clew/detect/structural.py:56-77`):
```python
if n < 2:
    raise ValueError("n must be >= 2 (a single occurrence is not a repeat)")
...
for occurrences in groups.values():
    if len(occurrences) < n:
        continue
    origin = occurrences[0]
    ...
    for cand in occurrences[1:]:
        ...
        pairs.append((origin, cand))
```

- N is the **occurrence-count threshold within a subgroup** (tool: `(agent_or_node_id, normalized_input)`; otherwise: `agent_or_node_id`).
- **It is not a window.** cascade (`src/clew/detect/cascade.py`) has no gap/distance argument. Two occurrences can be any number of turns apart (as long as no compact boundary intervenes) and still pair/fire as waste.
- N=k means: "if a subgroup has ≥ k occurrences, return pairs (first occurrence, each subsequent occurrence)".

### Q2 — actual causes of the §24.9 51 duplicated misses

`recon_N_window.py` Q2 tags each of the 51 misses after span→pair matching:

| reason | count |
|---|---:|
| `sha256_mismatch` (pair formed, output hashes differ) | 24 |
| `sha256_equal_but_not_in_waste` (hash equal, missing from cascade waste) | 27 |

**gap distribution** (first-occurrence turn → recurrence turn delta): n=51, min=**-3**, max=30, median=8, p25=3, p75=16.

- `sha256_mismatch` 24: legitimate miss. e.g. telecom `mobile_data_issue` timeout retry (error → success), retail re-lookup after state change (different output).
- `sha256_equal_but_not_in_waste` 27: **uncharacterized**. The recon script's span→pair matching logic includes abnormal cases like negative gap (-3). Separate verification required; only raw is recorded here.

**Decisive fact**: 30 of 51 misses have gap ≥ 6. **No matter how N is set (since it is a threshold, not a window), the distance between occurrences by itself does not block pairing.** Even at large gap, waste fires if sha256 matches. It misses at small gap if sha256 differs. **N is not a recall lever.**

### Q3 — N∈{2,3,5,∞} simulation (recon only, not applied)

**RB whole (airline 40 + retail 48 + telecom 112)**:

| N | tp | fp | fn | P | R | F1 | waste spans | traj_acc |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **2** | 218 | 46 | 1168 | 0.8258 | 0.1573 | **0.2642** | 132 | 0.5000 |
| 3 | 63 | 11 | 1323 | 0.8514 | 0.0455 | 0.0863 | 37 | 0.1735 |
| 5 | 8 | 0 | 1378 | 1.0000 | 0.0058 | 0.0115 | 4 | 0.0714 |
| ∞ | 0 | 0 | 1386 | 0.0000 | 0.0000 | 0.0000 | 0 | 0.0663 |

**CC (`~/.claude/projects/**/*.jsonl`, 50 ingested out of 54 sessions)**:

| N | sessions_with_waste | total_waste_spans |
|---:|---:|---:|
| **2** | 3 | 5 |
| 3 | 0 | 0 |
| 5 | 0 | 0 |
| ∞ | 0 | 0 |

### Q4 — Conclusion

- **N=2 is F1-optimal (4-value post-hoc comparison).** Monotonically decreasing. Same pattern across all 3 RB domains.
- **This optimality is a post-hoc observation, not a value derived by calibration.** Must be admitted openly.
- Recall ceiling: 30 of 51 misses have gap ≥ 6. These cannot be caught by tuning N (N is not a window). Introducing an **adjacency filter (a separate parameter W)** would require pre-registration; outside the scope of this recon.
- **Keep N=2.** Frozen target (`validation/CRITERIA_FROZEN.md`).

### Honesty boundary (§25 permitted / forbidden phrasing)

**Permitted**:
- "N=2 was confirmed as F1-optimal in a post-hoc comparison (RB 3 domains + CC 20 sessions, N∈{2,3,5,∞}; monotonically decreasing)."
- "N is an occurrence-count threshold, not a window (structural.py:69). cascade has no distance argument."
- "30 of 51 duplicated misses have gap≥6. Not resolvable by tuning N (a separate adjacency parameter would be required)."

**Forbidden**:
- "N=2 was derived by calibration" — grep shows no derivation procedure; it was an arbitrary default.
- Mentioning only "raising N trades recall for precision" without noting these are **measured post-hoc observations**.
- The §24.8 miss description's "outside N=2 window" phrase — **wrong**, corrected in §25.

### Deviation log — Rule 3 (surgical change)

When writing §24.7~§24.8, the "outside N=2 window" phrasing entered the SPEC layer without checking the code. **A pattern of unverified assumptions leaking into SPEC** (Rule 3 violation: unsupported claim). Prevention: any parameter mention must cite `src/clew/detect/*.py`; terms like "window/distance/N/φ" must start from the code definition.
