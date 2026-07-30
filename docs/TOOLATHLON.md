# §23 — Toolathlon adapter pre-registration (2026-07-18, Rule 8)

**Target data**: [hkust-nlp/Toolathlon-Trajectories](https://huggingface.co/datasets/hkust-nlp/Toolathlon-Trajectories) (HF, CC-BY-4.0, gated).

**Why a separate adapter**:
- On our 20 development sessions (§22.11.8), no candidates were upheld as waste after owner adjudication. The detector's true-positive capability cannot be demonstrated on this corpus.
- Toolathlon has 17 models × 3 runs × real long-horizon tool-use traces (with task success/failure labels). arXiv:2602.19008 names canonical path deviation as the failure cause → waste is likely to exist in reality.
- Recon (§23.5 evidence) confirmed re-invocations exist: of 108 traces, 39 (36%) contain (name, args) re-invocations, 177 candidates total.

**Recon artifacts** (Rule 7 addendum, bundled in the same commit):
- `field_test/diagnostics/recon_toolathlon.py` — schema recon (Q1–Q6)
- `field_test/diagnostics/recon_toolathlon_waste.py` — waste-reality check (Q1–Q5)

---

## §23.1 — Confirmed mapping (recon evidence)

| Span field | Toolathlon source | Evidence |
|---|---|---|
| `trace_id` | `request_id` (uuid string) | recon Q1 (`request_id` is unique) |
| `span_id` | `messages[i].tool_calls[j].id` (e.g. `toolu_01BFHkVg…`) | recon Q3 (join key), 10/10 match |
| `parent_span_id` | synthetic root (`root-<request_id>`) | CC precedent (`claude_code.py:203`) |
| `agent_or_node_id` | `tool_calls[j].function.name` | recon Q5 (206 unique tool names) |
| `span_kind` | `"tool"` | all tool calls |
| `input_text` | `json.dumps(json.loads(tool_calls[j].function.arguments), sort_keys=True, ensure_ascii=False)` | source is already a JSON string. As in the §22.2 CC precedent, **re-serialize with sort_keys** → stability of the sha256 gate |
| `output_text` | matching tool message `content` (raw string) | recon Q2 (no list content, flat string). If list format is found, reuse the §22.5 convention |
| `start_time` / `end_time` | synthetic (see §23.2) | recon Q4 |
| `token_count` | `None` | recon Q5 (`key_stats` is per-trace total only) |
| `model` | top-level `modelname_run` | recon Q5 |
| `cost_rate` | `None` (span unit unknown, `agent_cost` is per-trace total) | recon Q5 |

## §23.2 — Synthetic-timestamp convention

**Fact**: no per-message timestamp (recon Q5). Only top-level `initial_run_time` / `completion_time` exist; span-level distribution not possible.

**Convention**:
- Base: `base = 2026-01-01T00:00:00+00:00` (the detector only uses ordering, so the absolute value is meaningless; only monotonicity is needed)
- `start_time = base + timedelta(seconds = msg_idx * 1000 + sub_idx)`
  - `msg_idx`: index in the `messages` array (0-based)
  - `sub_idx`: order within that assistant message's `tool_calls` array (0-based)
- `end_time = start_time` (same)

**Justification**:
- Detector grep verification (2026-07-18): `src/clew/detect/structural.py:26,58,86` uses only `start_time` as an ordering key. No `end_time` ordering. `cascade.py:60` uses it only for the compact-window check (Toolathlon has no compact → no-op).
- recon Q4 observation: of 365 parallel-call messages
  - (name, args) duplicates within the same msg: **0** → no tie-break concern when using sub_idx for ordering
  - Cases where the result order was reversed: **0** → tool results arrive in `tool_calls`-array order
  → this convention preserves the origin ↔ candidate order.

**Limits**:
- This is an approximation. It is not real wall-clock, so gap(sec) = msg-index difference × 1000 (parallel = +1). Time-based statistics (gap describe etc.) are only interpretable on this scale.
- The §22.11 compact gate is a **no-op**: `Trace.metadata` does not contain `compact_boundaries`, so the existing `.get(key, [])` path automatically ignores it. Toolathlon has no CC-style compact concept.

## §23.3 — Deserialization caution

**Facts** (recon Q1):
- All 11 top-level fields are **JSON strings**. Fields requiring `json.loads()`: `task_status`, `config`, `tool_calls`, `messages`, `key_stats`, `agent_cost`.
- Plain strings: `modelname_run`, `task_name`, `request_id`, `initial_run_time`, `completion_time`.

**Adapter convention**:
- On per-field parse failure, **do not silently skip; raise `ValueError` explicitly** (§21.4).
- `tool_calls[j].function.arguments` is already a JSON string. Parse then re-serialize with `sort_keys=True` → sha256-gate stable.
- If `content` is in list form (Anthropic content blocks), reuse the §22.5 CC convention (block-by-block render + non-text blocks get `json.dumps` + warn). recon Q2 confirmed flat string, but full-file confirmation happens at adapter runtime.

**Join verification** (§22.4 precedent):
- The assistant-side call id set must equal the tool-side result tool_call_id set.
- On orphan presence, explicit error (log the first 5 ids).

## §23.4 — Detection dispatch

**Current state** (`src/clew/__main__.py:30`):
```python
if path.suffix == ".jsonl":
    from clew.ingest.claude_code import ingest_claude_code_jsonl
    return ingest_claude_code_jsonl(path)
```
→ the `.jsonl` extension unconditionally routes to CC. Toolathlon `.jsonl` also lands here.

**Revision**:
- After entering `.jsonl`, **peek the first-line JSON** and branch by top-level keys:
  - `modelname_run` AND `task_status` AND `messages` → Toolathlon
  - `sessionId` (CC marker) → CC
  - Otherwise explicit error (log first 5 top-level keys)
- The two marker sets **do not overlap** (CC has no `modelname_run`; Toolathlon has no `sessionId`).

**New module**: `src/clew/ingest/toolathlon.py`
- Function: `ingest_toolathlon_jsonl(path: Path) -> Trace`
- Each line in the file = 1 trace. **Not returning multiple Traces per file** — the adapter contract is "path → single Trace". Multi-trace files are iterated at the CLI level above.
- Provisional decision: `_load_trace_auto` returns **only the first trace** (contract identical to CC). Full-file scanning is exposed via the separate helper `iter_toolathlon_traces(path) -> Iterator[Trace]`, used in `field_test/diagnostics/scan_toolathlon.py`.

## §23.5 — Predictions before rerun (before seeing results)

**Target**: the received file `claude-4.5-sonnet-0929_1.jsonl` (108 traces). Run adapter + 3-stage gate (structural → sha256 → compact) on all 108.

recon was a provisional definition (python dict groupby). The adapter goes through the clew structural gate (`find_candidates`, N=2), so counts may differ.

| Metric | recon provisional | Prediction |
|---|---|---|
| repeat candidates (structural gate passed) | 177 | **150 – 177** (similar if definition same; the N=2 structural gate may see adjacency more strictly) |
| sha256 gate passed (tool kind) | 32 | **25 – 35** (should be close to recon simulation) |
| compact gate no-op confirmed | — | no key in Trace.metadata → cascade `.get(..., [])` passes, 0 excluded |
| Final waste (candidate span count) | — | **25 – 35** |

**Prediction grounding**:
- The sha256 gate must be close to the recon sim (32) for the adapter join to be correct. Large deviation = adapter join/parse bug.
- Empty-argument (args='') repeats will be included in numbers. In the playwright browser workflow (`playwright_with_chunk-browser_snapshot_navigate_to_next_span`, args=''), 4 sessions have count 7~13. These are "candidates, not confirmed waste" — as with the CC ExitPlanMode precedent, owner adjudication needed.

**If wrong, record it as wrong.**

### Negative-result definition
- If waste (sha256 gate passed) deviates from recon sim (32) by ±10 or more, it is an adapter join/parse difference. Root-cause in (§23.7 result section); keep the definition.

### Stop conditions
1. Existing 204 tests regress → halt. Do not fix tests to pass.
2. CC / OTel / OpenInference results change → halt. The Toolathlon branch must be independent (no adapter-file modifications other than adding a `_load_trace_auto` branch).
3. φ / N / model / sha256 logic needs changing → halt immediately (recheck §22.10 rule).
4. Span data structure needs extending → halt immediately (as in §22.11 precedent, only `Trace.metadata` extension allowed).

---

## §23.6 — Rule 8 commit chain (pre-registration timestamp proof)

This document (§23.1–§23.5) + 2 recon scripts = **pre-registration commit**.
- push → server timestamp stamped.
- Adapter implementation code is a **separate commit after push confirmation**.
- PR / merge is for after §23 is complete, on the entire feat/cc-adapter branch (separate request).

## §23.7 — Rerun results (2026-07-18)

**Run**: `python field_test/diagnostics/scan_toolathlon.py data/toolathlon/claude-4.5-sonnet-0929_1.jsonl`
**Gates**: φ=0.514345, N=2, model=paraphrase-multilingual-MiniLM-L12-v2@e8f8c21, sha256 tool-kind ON.
**Elapsed**: wall 0.7s.

### Prediction vs. observed

| Metric | Prediction (§23.5) | Observed | Verdict |
|---|---|---|---|
| repeat candidates (structural gate N=2) | 150–177 | **173** | ✓ in range |
| sha256 gate passed (tool kind) | 25–35 | **28** | ✓ in range |
| Final waste | 25–35 | **28** | ✓ in range |

All three predictions hit. Vs. recon provisional (177 candidates / 32 sha), -4 / -4 — the structural gate narrows more than recon's dict-groupby because of the N=2 adjacency condition, consistent with the pre-registration prediction.

### Load summary

- File line count: 108
- cascade executed successfully: **107**
- build exception: **1** — `line#30 [build] ValueError: arguments JSON parse failed (raw first 80 chars: '{"path": "/workspace/dumps/workspace/format_data.py"')`
  - **Cause**: real-data `filesystem-write_file` arguments value truncated at 52 chars (task=`quantitative-financial-analysis`, request_id=`671bb135-6a28-4ffa-acac-24374c8aa93b`). Defect in the Toolathlon dataset source.
  - **Handling**: adapter raises explicitly per §21.4. The scan script catches per-line and continues processing the remaining 107.
  - Only the scan script tolerates; the adapter contract (1 line → 1 Trace or ValueError) unchanged.

### waste > 0 trace distribution (14 traces)

| task_name | eval | waste count |
|---|---|---|
| k8s-pr-preview-testing | False | 8 |
| email-paper-homepage | False | 3 |
| reimbursement-form-filler | True | 3 |
| fillout-online-forms | True | 2 |
| (remaining 10 traces: 1–2 each) | mix | 12 |

**Waste rate by evaluation**:
- eval=`False` (63 failed): waste 21, waste-traces 11 (17.5%)
- eval=`True` (44 succeeded): waste 7, waste-traces 3 (6.8%)

Failed traces show a **2.6×** waste-trace ratio vs. successful traces. Consistent with the arXiv:2602.19008 "canonical path deviation → failure" direction (not statistics, observation).

### waste tool distribution

**With args (27)** — top:
- `filesystem-read_file` 5
- `pdf-tools-read_pdf_pages` 4
- `github-get_file_contents` 4
- `playwright_with_chunk-browser_type` 2
- `k8s-kubectl_get` 2
- `playwright_with_chunk-browser_navigate` 2
- `playwright_with_chunk-browser_wait_for` 2
- (other 6 tools × 1 each)

**args='' or '{}' (1)**: `playwright_with_chunk-browser_close` args=`{}` × 1

recon prediction: "playwright next_span args='' repeats will be included in numbers" — **wrong**. The sha256 gate filtered out most args='' repeats (different page → different snapshot → sha256 mismatch). As with the CC ExitPlanMode precedent, even without args, output must match to be waste — but playwright next_span normally advances to a different page per call, so outputs differ. Result: playwright next_span waste=0.

### Adapter implementation notes (fine tuning vs. pre-registration)

- `_normalize_arguments`: raw=`""` (empty string) is Toolathlon convention for "no arguments", so normalize to `{}`. The pre-registration (§23.3) only stated "raise on parse failure"; the empty string is not a parse failure, but a convention. The adapter test `test_arguments_parse_failure_raises` targets truly malformed strings like "not valid json!!".
- Still, malformed JSON (line-30 case) hard-raises. §21.4 respected.

### Stop-condition recheck

1. **204 regression** — 216 pass (12 new included). No regression.
2. **CC/OTel/OpenInference result change** — only the `_load_trace_auto` branch logic expanded. CC test `test_auto_dispatch_cc_still_works` passes. No other adapter files modified.
3. **φ / N / model / sha256 logic change** — none.
4. **Span data-structure extension** — none. Only added `source, task_name, task_status, modelname_run` to `Trace.metadata`.

### Merge policy

- This commit is the §23 result commit on the `feat/cc-adapter` branch (pre-registration e8da282 → implementation → result).
- push only. PR is separate request (Rule 8 batched PR plan).

---

## §26 — 22-model expansion scan (2026-07-18, post-hoc, roadmap ③)

Reuse the §23 adapter (main-merged `52a38ea`) **unmodified**. `snapshot_download` the full `hkust-nlp/Toolathlon-Trajectories` → 66 files (22 models × 3 runs). Script: `field_test/diagnostics/scan_toolathlon_17models.py` (Rule 7 addendum).

### §26.1 — Scale

- **66 files, 7,116 traces** (some files 106, rest 108).
- **spans 183,050, tool spans 176,270.**
- **17,101 repeat candidates** (structural gate N=2 passed).
- **8,042 waste** (sha256 gate additionally passed), **waste_traces 1,280.**
- **eval distribution**: `pass=1,613  fail=5,046  other=121` (remaining 336 = parse-failed lines).
- **wall time**: 32.1 s (after embedding cache warm; labels not referenced).

### §26.2 — Per-model waste density (aggregated over 3 runs)

```
model                    trc   cnd   wst   wT  w/trc  w/1kt   sha%  wf/tf  wp/tp
claude-4-sonnet-0514     324   360    59   33  0.182   6.84  16.4%  0.232  0.085
claude-4.5-haiku-1001    324   536   104   52  0.321   9.68  19.4%  0.363  0.202
claude-4.5-opus          324   756   195   46  0.602  18.31  25.8%  0.485  0.128
claude-4.5-sonnet-0929   324   465    89   38  0.275   8.97  19.1%  0.271  0.285
deepseek-3.2-thinking    324   801   259   78  0.799  20.77  32.3%  0.500  0.477
deepseek-v3.2-exp        324   478   220   57  0.679  27.81  46.0%  0.450  0.156
gemini-2.5-flash         324   741   330   69  1.019  94.53  44.5%  0.869  0.583
gemini-2.5-pro           324  4246  2742  110  8.463 286.43  64.6%  2.378  0.500
gemini-3-pro-preview     324   483   172   41  0.531  22.92  35.6%  0.401  0.169
glm-4.6                  324   856   137   45  0.423  15.34  16.0%  0.427  0.067
gpt-5                    324   226   113   48  0.349  15.49  50.0%  0.447  0.235
gpt-5-high               324   159    51   35  0.157   8.24  32.1%  0.199  0.144
gpt-5-mini               324   687   378   87  1.167  50.43  55.0%  1.490  0.217
gpt-5.1                  324   357   100   43  0.309  12.33  28.0%  0.206  0.552
grok-4                   320  1196   471   91  1.472  55.02  39.4%  1.354  1.854
grok-4-fast              320  1477  1081   44  3.378 130.12  73.2%  4.127  0.133
grok-code-fast-1         320  1189   668   39  2.087  87.70  56.2%  2.541  0.250
kimi-k2-0905             324   458   136   54  0.420  18.44  29.7%  0.536  0.171
minimax-m2               324   228    64   35  0.198  11.42  28.1%  0.213  0.091
o3                       324   384   190   58  0.586  32.51  49.5%  0.724  0.218
o4-mini                  324   305   305   91  0.941  57.79  70.3%  0.925  0.500
qwen-3-coder             324   584   178   86  0.549  20.28  30.5%  0.631  0.340
```

Legend: `w/trc` = waste/trace, `w/1kt` = waste/1,000 tool spans, `sha%` = waste/cands (sha256 gate pass rate), `wf/tf` = waste / failed-trace, `wp/tp` = waste / passed-trace.

- **w/trc max = gemini-2.5-pro 8.463** (2,742 waste / 324 traces).
- **w/trc min = gpt-5-high 0.157** (51 waste). **54× spread.**

### §26.3 — sha256 gate generality + empty-arg distribution

- Overall `sha%` = 8,042 / 17,101 = **47.0%**.
- Per-model `sha%` range: **16.0% (glm-4.6) — 73.2% (grok-4-fast).**
- claude-4.5-sonnet-0929 sha% 19.1% (near the §23.7 baseline 16.2%).
- **Empty-arg waste** (`input` ∈ {"", "{}"}):
  ```
  gemini-2.5-pro       645 / 2742
  grok-code-fast-1     185 /  668
  claude-4.5-opus      125 /  195   (64%)
  grok-4               123 /  471
  gpt-5                  0 /  113
  gpt-5-high             0 /   51
  ```
  gpt-5 family: 0 empty-arg. gemini / grok / claude-opus have substantial empty-arg waste.

### §26.4 — Honest correction: retract "failure 2.6×" (important)

**Retract §23.7 statement**: "failed traces show 2.6× waste (claude-4.5-sonnet, single)" was a **small-sample (108 traces) impression**. On the 22-model rerun, claude-4.5-sonnet-0929 gives `wf/tf 0.271 / wp/tp 0.285 = 0.95×` — the multiplier inverts. **Retracted.**

**Large-sample facts** (n=7,116, 22 models):
- Of 22 models, **18** have `wf/tf > wp/tp` (failed-trace waste density higher than passed).
- 4 models invert (passed > failed): `claude-4.5-sonnet-0929 (0.271 vs 0.285)`, `gpt-5.1 (0.206 vs 0.552)`, `grok-4 (1.354 vs 1.854)`, `qwen-3-coder (0.631 vs 0.340)`.
- The multiplier varies per model (e.g. `grok-4-fast 4.127 / 0.133 = 31×`; `gpt-5-mini 1.490 / 0.217 = 6.9×`; on the other side `gpt-5.1 0.206 / 0.552 = 0.37×`). **A single "N×" statement is not possible.**

**Can be said**: "In most models (18/22), failed traces have higher waste rates than passed."
**Cannot be said**: "Failed traces have N× more waste than passed" — on a large sample the multiplier itself is a function of the model, not a single constant.

**Deviation registered (Discipline 5 — count before generalizing)**: describing a 108-trace impression as a multiplier is refuted on 22 models. **Small-sample multipliers must be stated only as "observation"; no "multiplier" assertion.**

### §26.5 — Tool category distribution (all waste 8,042)

```
read     : 3,536  (44.0%)
other    : 2,583  (32.1%)
write    : 1,069  (13.3%)
browser  :   524  ( 6.5%)
execute  :   330  ( 4.1%)
```

**Tool name top-10**:
```
1478  [read   ]  github-get_file_contents
1042  [other  ]  local-claim_done
 826  [read   ]  filesystem-read_file
 460  [write  ]  emails-send_email
 403  [read   ]  pdf-tools-read_pdf_pages
 271  [read   ]  filesystem-list_directory
 262  [write  ]  filesystem-create_directory
 241  [browser]  playwright_with_chunk-browser_type
 194  [execute]  local-python-execute
 136  [execute]  terminal-run_command
```

**Model characteristics (raw)**:
- `grok-4-fast`: 1,022 read / 1,081 waste = **94.5% read** skew.
- `grok-code-fast-1`: **write 318** (largest absolute write among models).
- `claude-4.5-opus`: **execute 115** (largest execute among models).
- `gemini-2.5-flash`: **browser 165** (largest browser among models).
- `github-get_file_contents 1,478` largest — empirical requery_known (re-lookup of information that does not change).

### §26.6 — 336 parse failures (§21.4 re-confirmed)

- All failures come from the `_build_trace_from_entry` step `ValueError` (not silent skip; per-line raw log).
- Most common types:
  - `deepseek-3.2-thinking_*`: `Unterminated string starting at line 1 col ~10` (raw-escape failure inside code arg).
  - `claude-*_*`: `Expecting ',' delimiter` (backslash-escape error after `{"path": "…"`).
  - `deepseek-v3.2-exp_3`: `Expecting value` (`{"resourceType": …, "name": ,` — empty value).
- **Adapter contract unmodified** — malformed JSON raises per line, not per file skip.

### §26.7 — Honesty boundary (Toolathlon scope)

- Toolathlon provides **only pass/fail labels**. The **8,042 waste are candidates**, not confirmed waste (no step-level GT as in RB).
- Cite per the following rules:
  - "8,042 waste candidates detected / average 1.13 per trace" (√)
  - **Do not cite** "F1 / precision / recall" — no labels.
- **Axis split**:
  - **Scale · model-comparison axis** = Toolathlon (22 models × 3 runs, precision not measured).
  - **Precision axis** = RedundancyBench (F1 0.2642, human labels, single-domain set).
- **Usable** (raw citation): "At 22-model scale, per-trace waste-candidate density spread of 54× (0.157–8.463)."
- **Unusable**: "gemini-2.5-pro wastes 54× more than gpt-5-high" — no labels; this is candidate density, not confirmed waste. Task composition · success-rate confounds uncontrolled.

### §26.8 — Merge policy

- This commit is on the `feat/N-recon` branch (roadmap ② N recon + ③ Toolathlon expansion batched).
- push only. PR is at the end of roadmap ② ③, bundled.

---

## §27 — Cost calculation recon (2026-07-18, backlog, Phase 2)

**Purpose**: check citation viability of report.md's "waste = tokens X = $Y". Code-unmodified recon.
Script: `field_test/diagnostics/recon_cost_calc.py` (Rule 7 addendum).

### §27.1 — Report pipe is ready

- `src/clew/report/markdown.py:60-67, 79-89`: `estimated wasted tokens/cost` slots already exist. If value absent, `"unknown"`.
- `src/clew/report/_model.py::WasteDetail`: `waste_tokens = candidate.token_count`, `waste_cost = token_count × cost_rate`.
- `src/clew/detect/cascade.py:70-77`: waste-aggregation logic exists (`tc = s.token_count or 0`).
- **So as soon as the adapter fills `Span.token_count` / `Span.cost_rate`, the report auto-displays them.**

### §27.2 — Per-adapter fill state (current report cost is all "unknown")

| Adapter | token_count | cost_rate | model |
|---|---|---|---|
| `claude_code.py:223-225` | None | None | None |
| `redundancy_bench.py:226-228` | None | None | None |
| `toolathlon.py:210-212` | None | None | `modelname_run` (file name) |
| `langgraph.py:127-129` | `_token_count_of(attrs)` | `cost_table[model]` | `model` |
| `otel_json.py` | (same utility as langgraph) | — | — |

- **Adapters that can directly count waste-span tokens** = only LangGraph / OTel JSON. The CC / RB / Toolathlon we actually scanned are all unfilled.

### §27.3 — CC has the data but not the mapping

CC JSONL source `type: "assistant"` message usage:
```
{'input_tokens': 3, 'cache_creation_input_tokens': 10705,
 'cache_read_input_tokens': 13305, 'output_tokens': 195, ...}
```
- Usage is **attached to the assistant (LLM) message**.
- The Clew CC adapter **only produces tool spans** (no LLM spans). → present in source, not captured by the adapter.
- To inject tokens: (a) introduce LLM spans, or (b) attribute adjacent assistant usage to the tool span. **Structural decision required (Phase 2).**

### §27.4 — Char-based approximation

- `tiktoken` not installed. Alternative: `chars/4` median, range `chars/5..3`.
- JSON/code near `chars/3`, natural language `chars/4`. No single-value "exact token" statement.
- Waste = origin·cand output_text same sha256 → cand output_text char count ≈ re-consumed context size.

### §27.5 — Key insight: multi-turn amplification

- **Simple re-consumption $ is small**: Toolathlon 8,042 waste × chars/4 × input $3/M = **~$9.76** (all 22 models × 3 runs, per trace $0.00137).
- **Real waste = tool_result re-consumed as LLM input on every subsequent turn × remaining turn count.**
  - i.e. amplification factor ≈ (assistant turns remaining after waste-span appearance).
  - Consistent with the arXiv:2509.23586 argument (tool messages, 30.4K token repeated waste).
- Accurate amplification modeling (turn count, cache_read vs. input distinction) is separate work. **Phase 2 backlog.**

### §27.6 — Unit-price handling

- Unit price is time-variant → **no hardcoding**. Recommend user input / env / external table.
- 2026-07 approx (do not cite; recon reference values):
  - Anthropic Claude 4.5 Sonnet: input $3/M, output $15/M
  - OpenAI GPT-5: input $2.50/M, output $10/M
- `Span.cost_rate` is a **single $/token** (no input/output split). Precise costing requires Span extension.

### §27.7 — Backlog state

- **Phase 2 kickoff conditions**: (a) adapter token mapping (CC LLM-span introduction decision), (b) amplification model pre-registration, (c) unit-price injection interface.
- **Not started before README / external citation** — report cost remains "unknown".
- **Can be said** (now): "waste = tokens X = $Y pipe is ready. Awaiting adapter extension."
- **Cannot be said**: "Saved $X" — no adapter computes $ in the report; only recon approximation.
