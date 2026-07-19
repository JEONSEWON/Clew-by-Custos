# Clew — Waste Pattern Precision Diagnosis Log

An honest record — for each of the three waste patterns the project originally named
(repeat_node / pingpong / requery_known) — of its actual state in the code and
its empirically observed detection cases. A fold-back log that records observed
facts only, without touching detection logic or frozen parameters.

## §28 — Precision Diagnosis of the Three Waste Patterns (2026-07-18)

### repeat_node — operational (the only empirically observed detection path)

- Function: `find_repeat_candidates(trace, n)` (`src/clew/detect/structural.py:48`).
  N=2 is not a window — it is an **occurrence count threshold** (§25).
- Subgroup keys:
  - `span_kind == "tool"` → `(agent_or_node_id, _normalize_input(input_text))`
    (`structural.py:20`: `strip().casefold()`)
  - other kinds → `(agent_or_node_id, None)`
- SPEC §16 parent-AGENT gate: if the nearest ancestor AGENT of the two spans
  differs, the pair is excluded.
- Empirical firings:
  - 5+ CC cases (§22.11.8, session 2502fe9a etc.)
  - RedundancyBench 218 predictions (§24.7, F1=0.2642 precision=0.8258)
  - Toolathlon 22-model scan, 8,042 waste (§26) — all through this function path

### pingpong — implemented but zero empirical firings (doubly blocked)

- Function: `find_pingpong_candidates(trace)` (`structural.py:80–104`).
- Firing condition: a time-ordered 4-window `A→B→A→B` where (a) all four spans
  have `span_kind == "llm"` AND (b) `agent_or_node_id` satisfies
  `A == A' ≠ B == B'` AND (c) strict adjacency
  (`ordered[i], ordered[i+1], ordered[i+2], ordered[i+3]`). A very narrow pattern
  (theoretically a multi-agent supervisor/worker router bounce).
- **Blocker ①** — adapters do not emit LLM spans:
  - `src/clew/ingest/claude_code.py:212–227`: every span is hardcoded to
    `span_kind="tool"`. `claude_code.py:152–154` does not spanify
    `thinking`/`text` blocks (§22.3).
  - `src/clew/ingest/toolathlon.py:6` docstring: "synthetic CHAIN root + tool
    spans only".
  - `src/clew/ingest/redundancy_bench.py:216–230`: every matched_pair is emitted
    with `span_kind="tool"`. Assistant text is not spanified (§24.2).
- **Blocker ②** — OTel/LangGraph do emit LLM spans, but preprocess strips them:
  - `src/clew/ingest/langgraph.py:32–38` `_KIND_MAP`: `"LLM": "llm"` mapping
    exists.
  - The official entrypoint `ingest_otel_spans` (`langgraph.py:148–161`) always
    calls `preprocess_trace()`.
  - `src/clew/ingest/preprocess.py:94–146` `collapse_llm_spans` **removes every**
    span with `span_kind == "llm"` (token_count is rolled up into the parent
    chain; ReAct children are re-parented).
  - Result: even traces that pass through OTel/LangGraph end up with zero llm
    spans → pingpong is always 0.
- **Sole firing path**: `eval/generators/patterns/pingpong_aba.py` (synthetic).
  It builds the trace directly, bypasses preprocess, and assigns
  `span_kind="llm"` explicitly (lines 54, 63, 72, 81). The pingpong component
  of the synthetic F1=0.857 evaluation runs exclusively through this path.
- All three real adapter outputs (CC 6,780 tool spans / Toolathlon 176,270 tool
  spans / RB 1,628 tool spans) show zero firings.
- **Honest labeling**: "implemented ≠ observed". Coding/tool agents are
  dominated by single-agent setups, so an A→B→A→B LLM back-and-forth is
  structurally absent. Once multi-agent traces are available, we will
  (1) confirm real back-and-forth occurs, (2) recon whether the pingpong
  definition fits, (3) enable llm spans → turn it on after verification.
  **Not advertised until verified.**

### requery_known — no separate function; absorbed as a tool subgroup of repeat

- `structural.py:1–13` comment:
  > "requery: a special case of repeated tool nodes → subgrouping already
  > handles it."
- Definition: `requery ≡ (repeat AND span_kind == "tool" AND normalize(input) matches)`.
- Because `find_repeat_candidates` uses `(name, normalize(input))` as its tool
  subgroup key, re-calls of the same tool with the same argument naturally
  cluster into the same group. No separate detect function is needed
  = **avoids reinvention, correct by design**.
- Empirical coverage:
  - RedundancyBench `duplicated step` (the requery label) recall 0.6077
    (79/130, `docs/REDUNDANCY_BENCH.md §24.4`).
  - All 8,042 Toolathlon waste cases are tool spans → all through this path.
- 40% misses (of the 51 RB misses, 30 have gap≥6): N=2 is an occurrence count,
  not a window, so these are uncoverable (§24.9 / §25). Documented as a recall
  ceiling.

### §28.1 — Label Scheme Backlog (no detect change, Phase 2 candidate)

**Current state — pattern label not preserved**:
- `CascadeResult` (`src/clew/detect/cascade.py:32–37`) field:
  `waste_span_ids: list[str]`. No pattern label field (flat list).
- `find_candidates` (`structural.py:107–117`) merges the results of
  `find_repeat_candidates` + `find_pingpong_candidates` and returns
  `list[tuple[Span, Span]]`. The information about which pattern produced each
  pair is lost.
- The "repeat_node" string in `src/clew/report/markdown.py:73` is only a column
  header (it shows the `agent_or_node_id` of the recurring span). It is not a
  pattern label.

**Minimum change proposal (no impact on frozen / gates / thresholds; pre-1.0 schema extension)**:
1. Add a kind tag to the `find_candidates` return:
   `list[tuple[Span, Span, str]]` where kind ∈ {`"repeat"`, `"requery"`, `"pingpong"`}.
   Alternatively, introduce a new `find_candidates_labeled` function.
2. Add a `CascadeResult.waste_labels: dict[str, str]` field
   (span_id → pattern name).
3. Add a "pattern" column to the `markdown.py` / `json_report.py` renderers.
4. `requery` becomes a derived label from
   `(repeat AND kind == "tool" AND normalize(input) matches)`. No new detect
   function.

**Value**: makes reports more concrete (Toolathlon 8,042 could be labeled
"all requery"; the RB duplicated recall could be surfaced directly in the
report).

**Risk**: none (detection decisions unchanged; most tests unchanged).
**Out of roadmap — separate decision.**
