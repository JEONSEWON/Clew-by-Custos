# Clew

**Detect wasteful loops and redundant handoffs in multi-agent AI traces.**

Clew takes a trace from any OpenInference-instrumented framework and reports which spans are doing redundant work — repeated node calls, ping-pong handoffs, re-querying known results — along with estimated wasted tokens and cost.

**Current status: Stage 18 complete — requery FP diagnosis done; first real-data true-positive confirmed (Stage 17); parent-AGENT gate added (Stage 16); OTel-JSON generalized (Stage 12).**

---

## How it works

Clew runs a two-layer cascade detector on a normalized span tree:

1. **Structural layer** — finds repeated nodes, ping-pong patterns, and duplicate tool calls (input gate included)
2. **Semantic layer** — confirms waste via cosine similarity (φ gate) on span output embeddings

Frozen parameters: φ=0.514345, N=2, `paraphrase-multilingual-MiniLM-L12-v2`

---

## Quickstart

**Install**
```bash
pip install -e ".[adapter,detect]"
```

**Option A — Analyze any OTel SDK JSON file (any framework)**

Export your spans to a file, then analyze:

```python
import json
from pathlib import Path
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from openinference.instrumentation.langchain import LangChainInstrumentor  # or CrewAI, LlamaIndex, etc.

exporter = InMemorySpanExporter()
provider = TracerProvider()
provider.add_span_processor(SimpleSpanProcessor(exporter))
LangChainInstrumentor().instrument(tracer_provider=provider)

# run your app here

spans = exporter.get_finished_spans()
Path("trace.json").write_text(
    json.dumps([json.loads(s.to_json()) for s in spans])
)
```

```bash
python -m clew analyze trace.json
python -m clew analyze trace.json --out report.md
python -m clew analyze trace.json --json report.json
```

**Option B — LangGraph one-liner**
```python
from clew.capture import capture_langgraph
from pathlib import Path

trace = capture_langgraph(app, {"topic": "..."}, Path("trace.json"))
```

```bash
python -m clew analyze trace.json --out report.md
```

**Try the included example**
```bash
python -m clew analyze examples/sample_otel_trace.json
```

---

## Supported frameworks

Any framework instrumented with [OpenInference](https://github.com/Arize-ai/openinference):

| Framework | Instrumentation package |
|-----------|------------------------|
| LangChain / LangGraph | `openinference-instrumentation-langchain` |
| CrewAI | `openinference-instrumentation-crewai` |
| LlamaIndex | `openinference-instrumentation-llama-index` |
| OpenAI client | `openinference-instrumentation-openai` |
| AutoGen | `openinference-instrumentation-autogen` |

See `examples/README.md` for setup snippets per framework.

---

## Input formats

| Format | Description | Status |
|--------|-------------|--------|
| OTel SDK JSON array | `[json.loads(s.to_json()) for s in spans]` | ✅ Supported |
| Clew Trace JSON | Output of `save_trace()` | ✅ Supported (backward compat) |
| OTLP proto-JSON (`resource_spans`) | `encode_spans()` + `MessageToDict()` | 🔲 Planned (Stage 12-B) |

---

## Running tests

```bash
python tasks.py install        # install all dependencies
python tasks.py test           # run all tests (188)
python tasks.py check-leak     # label leakage guard only
python tasks.py dod            # DoD checks
python tasks.py all            # install → generate-set → test → check-leak
```

Or directly with `uv`:
```bash
uv sync --extra adapter --extra detect --extra dev
uv run pytest -v
```

---

## Project structure

```
src/clew/
  model.py                  Canonical span tree (Pydantic v2)
  ingest/
    langgraph.py            OTel ReadableSpan list → Trace (otel_spans_to_trace, ingest_otel_spans)
    otel_json.py            OTel SDK JSON file → Trace (ingest_from_otel_json)  ← NEW
    preprocess.py           JSON extraction, llm collapse, router filter
  detect/
    structural.py           Repeat / ping-pong / requery candidate detection
    semantic.py             Cosine similarity φ gate
    cascade.py              Two-layer cascade detector
  report/
    markdown.py             Markdown waste report
    json_report.py          JSON waste report
  capture.py                LangGraph capture helper (capture_langgraph)
  __main__.py               CLI — auto-detects OTel JSON or Clew Trace JSON

eval/                       Synthetic label set + evaluation harness
field_test/                 Real LangGraph app factories + real-trace probe scripts
examples/
  sample_otel_trace.json    Runnable 5-span example trace
  README.md                 Per-framework export snippets
validation/
  CRITERIA_FROZEN.md        Success/abort criteria — frozen before label inspection
tests/                      171+ gate tests
```

---

## Validation results

### Synthetic evaluation (Stage 2 GO, 2026-06-09)

| Metric | Value |
|--------|-------|
| F1 | **0.8571** |
| FPR | **0.0000** |
| TP / FP / TN / FN | 30 / 0 / 40 / 10 |
| Eval runs | 1 (criteria frozen before inspection) |

Per-pattern TPR:

| Pattern | TPR | Status |
|---------|-----|--------|
| repeat_node | 1.0 | ✅ Detected |
| pingpong_aba | 1.0 | ✅ Detected |
| requery_known | 1.0 | ✅ Detected |
| regen_handoff | 0.0 | 🔲 Out of v1 scope (no structural signal) |

### Real-trace probe (E1–E3, 2026-06-16)

5 real Claude Haiku traces, topic: 'quantum computing basics'. 5/5 PASS.

| Scenario | Expected | Detected | Result |
|----------|----------|----------|--------|
| clean (FP=0 baseline) | no waste | no waste | **PASS** |
| repeat_node | waste | waste | **PASS** |
| requery_known | waste | waste | **PASS** |
| requery_clean (negative control) | no waste | no waste | **PASS** |
| pingpong | waste | waste | **PASS** |

Tag: `real-probe-v1`

### E3 finding — semantic layer limitation (honest record)

Non-waste span cosines were above φ (0.514) in all scenarios (above-φ 100%, min 0.59–0.71). The '0.48–0.57 cluster' predicted from synthetic data did not appear in real traces — likely due to shared vocabulary across same-topic outputs.

**Interpretation:** FP=0 is a result of the structural layer (no repeat candidates generated), not the semantic φ gate. φ-transfer is a stronger problem than expected.

**Limitation:** n=1 topic, 5 traces. Results may differ across topics and domains.

### Stage 16 — parent-AGENT gate (structural fix, 2026-07-12)

Added parent-AGENT identity check to the structural layer: different-agent spans with the same node name are no longer treated as `repeat_node` candidates. TRAIL FP count dropped from 7 to 0; synthetic F1 0.857 / FPR 0 preserved.

### Stage 17 — real-waste hunt on TRAIL traces (2026-07-12)

40 TRAIL traces (GAIA + SWE Bench), stage 16 gate active.

| Metric | Value |
|--------|-------|
| Traces processed | 40 |
| FIRE before gate | 75 |
| FIRE after gate | 18 |
| True waste (human) | **1** (G8 — same-URL revisit, `requery_known`) |
| FP (human) | 17 |

**First real-data true-positive confirmed.** G8: agent revisited the same Wikipedia URL 46 seconds later with no content change; tool explicitly noted "previously visited."

Two improvement targets identified:
- (a) `requery_known` gate checks input equality but not URL/target identity — same search string on different URLs generates FP.
- (b) Origin selection picks the wrong anchor span, missing true-duplicate pairs (e.g., G3: 3 visits to issue #22104 undetected because origin was anchored to #9533).

### Stage 18 — requery FP diagnosis (2026-07-12)

80 TRAIL traces, 8 `requery_known` FIREs (tool+same-input gate active).

| Verdict | Count |
|---------|-------|
| True waste | 1 (#5 — tool confirmed "previously visited 46 s ago") |
| FP (different target) | 6 |
| FP (ambiguous) | 1 |

**Key findings:**
- **Cosine disproved as requery signal.** True waste cosine (0.9639) was *lower* than two FP pairs (0.9757) — φ adjustment cannot separate them. High cosine on FP cases is caused by shared "search string not found" boilerplate.
- **Target identity = preliminary signal (FP suppression, not new detection).** When target (URL/address) differs, verdict is always FP (6/6 cases, 0 counterexamples). But n=1 true-waste case is already identified by tool-reported re-visit, so target-identity gate's unique contribution is FP suppression (6 cases), not additional true-waste detection.
- **Data limit:** Only 8 FIRE cases available from TRAIL (source exhausted). Findings are preliminary; final validation requires real-workload traces (e.g., KAIST pipeline).

**Next step (Stage 19):** Design URL-aware requery gate with goal explicitly scoped to FP suppression. Generalize target extraction beyond TRAIL-specific "Address:" regex. Final gate validation on real-workload traces only.

---

## Integrity rules

- Criteria in `validation/CRITERIA_FROZEN.md` are never modified after label inspection.
- `src/clew/` never imports or reads `eval/labels*` — enforced by leakage guard tests.
- F1=0.857 was achieved on our own synthetic dataset. Not an external benchmark result.
- φ=0.514345 is frozen. Not adjusted based on real-trace observations.
