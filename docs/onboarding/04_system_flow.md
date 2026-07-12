# 04 — System Flow: Trace Input to Report Output

End-to-end data flow from an OTel JSON file on disk to a markdown or JSON waste report.

---

## ASCII Flow Diagram

```
  OTel SDK JSON file (Format A)
  — list of span.to_json() dicts, each with a "context" key —
          │
          ▼
  ┌───────────────────────┐
  │  _load_trace_auto()   │  src/clew/__main__.py
  │  Format detection:    │
  │  • dict + trace_id    │──→ load_trace()            (Clew native JSON)
  │  • list + context     │──→ ingest_from_otel_json() (Format A ✓)
  │  • resource_spans     │──→ ValueError + guide      (Format B ✗)
  └───────────────────────┘
          │
          ▼ (Format A path)
  ┌───────────────────────────────────────────────────┐
  │  ingest_from_otel_json()   src/clew/ingest/        │
  │  otel_json.py              otel_spans_to_trace()   │
  │                              ReadableSpan → Span   │
  │                            preprocess_trace()      │
  │                              Stage 1: extract_output_text     │
  │                              Stage 2: mark_worker_span_ids    │
  │                              Stage 3: collapse_llm_spans      │
  │                              Stage 4: filter_router_spans     │
  └───────────────────────────────────────────────────┘
          │
          ▼
  Canonical Trace (Pydantic-validated)
  — root 1개, 고아/사이클 없음, output_text 비어있지 않음 —
          │
          ▼
  ┌───────────────────────────────────────────────────┐
  │  cascade(trace, embedder, n=2, phi=0.514345)      │
  │  src/clew/detect/cascade.py                       │
  │                                                   │
  │  Stage 1 — Structural                             │
  │    find_candidates(n=2)                           │
  │    ├─ find_repeat_candidates()  same agent >= N   │
  │    └─ find_pingpong_candidates() A→B→A→B pattern │
  │                                                   │
  │  Stage 2 — Semantic (per candidate pair)          │
  │    cosine(embed(origin.output), embed(cand.output)│
  │    if >= phi → mark as waste                      │
  └───────────────────────────────────────────────────┘
          │
          ▼
  CascadeResult
  (wasteful, waste_span_ids, waste_tokens, waste_cost)
          │
          ├──────────────────────────────────────────────┐
          ▼                                              ▼
  ┌─────────────────────┐                  ┌─────────────────────┐
  │  render_markdown()  │                  │  render_json()      │
  │  src/clew/report/   │                  │  src/clew/report/   │
  │  markdown.py        │                  │  json_report.py     │
  └─────────────────────┘                  └─────────────────────┘
          │                                              │
          ▼                                              ▼
   report.md (stdout or --out)              report.json (--json)
```

---

## Step-by-Step Explanation

### 1. Format Detection (`_load_trace_auto`)

The CLI reads the file as UTF-8, parses JSON, and inspects the top-level structure.
Format A (supported) is a JSON array where `obj[0]["context"]` exists — this is the
direct output of `span.to_json()` from the OpenTelemetry Python SDK.
Format B (OTLP proto-JSON with `resource_spans`) is explicitly rejected with a
printed conversion guide.

### 2. Raw Conversion (`otel_spans_to_trace`)

Maps OTel attribute keys to canonical `Span` fields:

| OTel attribute | Span field |
|---|---|
| `openinference.span.kind` | `span_kind` (via `_KIND_MAP`) |
| `output.value` | `output_text` (required, non-empty) |
| `input.value` | `input_text` |
| `llm.token_count.total` | `token_count` |
| `llm.model_name` / `llm.provider` | `model` |
| `context.trace_id` | `trace_id` |
| `context.span_id` | `span_id` |
| `parent_id` | `parent_span_id` |

### 3. Preprocessing (`preprocess_trace`)

Four stages transform raw spans into a clean logical tree before detection.
Details in `03_architecture.md`. After preprocessing, `Trace.metadata` records
`collapsed_llm_spans` and `filtered_router_spans` counts.

### 4. Detection (`cascade`)

Two-stage filter: structural pattern matching narrows the search to candidate pairs;
the semantic gate then checks whether the candidate's output is meaningfully similar
to the origin's output. Only pairs that pass both stages contribute to waste counts.

### 5. Report Rendering

`render_markdown()` and `render_json()` both receive `(trace, CascadeResult,
list[WasteDetail])`. `WasteDetail` carries the origin span, the waste span, and
the cosine score for that pair.

**Snippet rules:**
- By default, `output_text` of each waste span is truncated to **80 characters**
  (`snippet_len=80`).
- Pass `--no-snippets` to omit all text snippets from the report (useful for
  piping or when output contains sensitive content).

---

## CLI Reference

```
python -m clew analyze <trace.json> [OPTIONS]

Arguments:
  trace.json        Path to trace file (Clew JSON or OTel SDK JSON Format A)

Options:
  --out report.md   Write markdown report to file (default: stdout)
  --json out.json   Also write a machine-readable JSON report
  --no-snippets     Exclude output_text snippets from both reports
```

Exit code: `0` in all non-error cases (waste detected or not). `1` on file-not-found,
parse error, or import error.

---

## Execution Example

### Example 1 — Clean trace (no waste)

```
$ python -m clew analyze field_test/real_clean.json --no-snippets

# Clew Waste Report

- **trace_id**: `8841d5c2adfcf43fa97d890293be3916`
- **analyzed**: 2026-07-05T09:25:38Z
- **detector params**: φ=0.514345, N=2, model=paraphrase-multilingual-MiniLM-L12-v2

## Result: no waste detected

No wasteful patterns found (wasteful=False).

---
_Note: detection thresholds were calibrated on synthetic traces; real-trace
calibration is in progress. Borderline matches (cosine near 0.51) deserve
human review._
```

### Example 2 — Waste detected (repeat_node)

```
$ python -m clew analyze field_test/real_repeat_node.json --no-snippets

# Clew Waste Report

- **trace_id**: `5bab10406d1b9a3324324a72e0b9d428`
- **analyzed**: 2026-07-05T09:32:47Z
- **detector params**: φ=0.514345, N=2, model=paraphrase-multilingual-MiniLM-L12-v2

## Result: WASTE DETECTED

- **wasted spans**: 1
- **estimated wasted tokens**: unknown
- **estimated wasted cost**: unknown

## Wasted Span Details

| origin_node | repeat_node | cosine | tokens (wasted) | cost (wasted) |
|-------------|-------------|--------|-----------------|---------------|
| researcher  | researcher  | 1.0000 | unknown         | unknown       |

---
_Note: detection thresholds were calibrated on synthetic traces; real-trace
calibration is in progress. Borderline matches (cosine near 0.51) deserve
human review._
```

`tokens (wasted)` shows `unknown` when the span has no `token_count` — the real
probe traces were generated without token counting enabled in the cost table.

---

## JSON Report Structure

When `--json out.json` is used, the output follows this schema:

```json
{
  "trace_id": "5bab10406d1b9a3324324a72e0b9d428",
  "analyzed": "2026-07-05T09:32:47Z",
  "detector_params": {
    "phi": 0.514345,
    "n": 2,
    "model": "paraphrase-multilingual-MiniLM-L12-v2"
  },
  "wasteful": true,
  "waste_tokens": 0,
  "waste_cost": 0.0,
  "details": [
    {
      "origin_span_id": "...",
      "origin_node": "researcher",
      "candidate_span_id": "0f6dc5c36ee7de58",
      "repeat_node": "researcher",
      "cosine": 1.0,
      "waste_tokens": null,
      "waste_cost": null,
      "origin_snippet": null,
      "candidate_snippet": null
    }
  ]
}
```
