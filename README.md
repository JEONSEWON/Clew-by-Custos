# Clew

**Find where your coding agent wastes work: which file, which turn, why.**

```bash
pip install "clew-custos[detect]"
python -m clew analyze <trace>.jsonl --out report.md
```

> PyPI name is `clew-custos` (the bare name `clew` is an unrelated placeholder). The module still imports as `clew`.

**No instrumentation. No SDK. No code changes.** Clew reads trace files your agent already writes: Claude Code JSONL, OpenTelemetry SDK JSON, OpenInference (Phoenix / TRAIL), or its own native JSON.

Ran on 6,780 public benchmark trajectories. One Toolathlon Canvas session (`grok-4_2`, task `canvas-art-manager`) shows the shape of what falls out:

```
## Result

- **Waste detection**: no waste detected (wasteful=False).
- **Duplicate creation check**: 27 candidate pair(s) — 13 with differing entity IDs, 0 with the same entity ID, 14 without extractable entity ID. Detection, not confirmed impact. See section below.

- **Tool mapping coverage for this trace**: 11 of 15 tools recognized (73.3%).
- **Unrecognized tools in this trace (top 4)**: canvas-canvas_get_user_profile, canvas-canvas_health_check, canvas-canvas_list_sub_accounts, emails-download_attachment

## Duplicate creation check

The waste detector above requires both responses to be byte-identical. That is the right test for reads — a re-read that returns the same content is a redundant call. For creation tools it is reversed: if a document really was created twice, the two responses carry different entity IDs, so the waste detector excludes them by construction. This section scans that excluded pool separately.

- **candidates**: 27 pairs total
  - 13 with different entity IDs
  - 0 with the same entity ID
  - 14 without extractable entity ID

### 1. canvas-canvas_upload_file_from_path

- origin span `call_79190340` → candidate span `call_52801306`
- Both calls returned entity IDs, and they differ: 5 / 35.

### 2. canvas-canvas_upload_file_from_path

- origin span `call_94789037` → candidate span `call_89334053`
- Both calls returned entity IDs, and they differ: 7 / 32.
```

All 13 differing-ID pairs in this trace are the same tool, `canvas-canvas_upload_file_from_path`. The agent uploaded the same file 13 times, and each call created a distinct Canvas entity. The waste detector correctly did not flag them (the responses were not byte-identical, because each returned a different ID). The `Duplicate creation check` section catches exactly this reverse case.

Reproduce:

```bash
pip install "clew-custos[detect]"
# Toolathlon corpus (CC-BY-4.0): huggingface.co/datasets/tsinghua-mars-lab/toolathlon
python -m clew analyze grok-4_2.jsonl --out report.md
```

*(Yes, agents legitimately re-read files. That is why the cascade below has two gates: the structural group only becomes a flag when the state check confirms nothing changed between the two calls, and the tool output is byte-identical.)*

---

## Why diagnosis (and not another dashboard)

Observability tools (Langfuse, Phoenix, LangSmith) show you the trace. Clew tells you which spans are waste, and why: the exact file, the turns, whether the file was modified in between.

Clew diagnoses; it does not fix. What to change in your agent (prompt, context caching, tool routing) is a call only you can make.

Scope is deliberately narrow: one working pattern (`repeat` / `requery`), done precisely.

---

## How it works

A two-stage cascade, fully deterministic. Every parameter is pinned to a git tag with a manifest sha256.

**Stage 1: structural gate.** Group steps by `(node, normalized input)`. A group with `N ≥ 2` occurrences is a candidate.

**Stage 2: identity gate.** Compare the two outputs.

- **Tool spans**: require `sha256(output_A) == sha256(output_B)`. Byte-identical. This is the precision-carrying gate.
- **Non-tool spans**: require cosine similarity `≥ φ` against a frozen embedding (`paraphrase-multilingual-MiniLM-L12-v2`).

**Why sha256 for tools.** We cannot see inside a tool. We do not know whether `Bash: ls` had side effects, or whether `send_email` actually reached anyone. So we judge by result. Same input, same byte output, no state change in the interval: the second call was redundant. If outputs differ (a retry succeeded where one failed, an in-memory counter advanced), the pair is **not** flagged.

**Reverse case: duplicate creation.** If two `notion-API-post-page` calls really did create two pages, the responses carry different entity IDs, so byte-identity fails and the waste detector correctly excludes them. The `Duplicate creation check` section scans that excluded pool separately, using per-tool entity-ID extraction (26 tools currently mapped, see [`docs/ID_BRIDGE_PRODUCTION_PREREG.md`](https://github.com/JEONSEWON/Clew-by-Custos/blob/main/docs/ID_BRIDGE_PRODUCTION_PREREG.md) §1.1). This is what surfaced the 13 Canvas uploads above.

**Frozen parameters** (never hand-tuned): `φ = 0.514345`, `N = 2`. `N = 2` began as an arbitrary default; a later grid on `N ∈ {2, 3, 5, ∞}` on RedundancyBench found F1 decreases monotonically as `N` grows. F1-optimal, not tuned.

**State check.** For tool-repeat pairs the report says either "no modification of this file in between" or "**File was modified in between**, may be a legitimate re-read". Tool-error responses (`is_error: true` in Anthropic `tool_result`) are excluded with an explicit count.

**Report categories** (labels only; detection is unchanged):

- **`error_repeat`**: same call after a failure, same arguments as before.
- **`side_effect`**: state-changing tool invoked twice with the same arguments.
- **`idempotent`**: read-only or declarative tool called repeatedly. Sub-classified into a 5-value evidence tier; see [`docs/GREYZONE_EXPANSION_PREREG.md`](https://github.com/JEONSEWON/Clew-by-Custos/blob/main/docs/GREYZONE_EXPANSION_PREREG.md).
- **`unclassified`**: payload-dependent tools (`Bash`, `PowerShell`, `bigquery_run_query`). Tool name alone cannot classify.

Mapping is by exact tool name, never by substring.

---

## Reads your existing traces

Auto-detected input formats:

| Source | Detected by |
|---|---|
| Claude Code session logs (`.jsonl`) | `sessionId` |
| OpenTelemetry SDK JSON | `context` |
| OpenInference (Phoenix / TRAIL) | `span_id` + nested `child_spans` |
| Clew native trace JSON | `trace_id` + `spans` |
| Toolathlon trajectories | `modelname_run` + `task_status` |
| RedundancyBench | `tasks` + `simulations` |

*Cursor and Codex sessions are not supported yet.*

*OTLP protobuf-JSON is not yet supported; the error message points at the SDK-JSON conversion.*

### OpenInference framework coverage

Measured PASS on Tier 1 and Tier 2:

| Framework | Fixture | Notes |
|---|---|---|
| LangChain / LangGraph | ✔ `tests/fixtures/openinference_langchain.json` | JSON-wrapped `TOOL` output unwrapped by adapter. |
| CrewAI | ✔ `tests/fixtures/openinference_crewai.json` | `.run` / `._execute_core` suffixes stripped. |
| LlamaIndex | schema-shared | SDK wraps returns in `{"blocks":[...], "raw_output":<orig>, ...}`; `entity_id` path needs `raw_output.` prefix. |
| OpenAI Agents SDK | schema-shared | No envelope. |
| AutoGen | schema-shared | `entity_id` not extractable (Python `str(dict)` is not valid JSON). |
| Smolagents | schema-shared | `Tool.__call__` wrap; end-to-end cascade verified. |

Full results and per-instrumentor path table: [`docs/OPENINFERENCE_FRAMEWORK_EXPANSION_RESULTS.md`](https://github.com/JEONSEWON/Clew-by-Custos/blob/main/docs/OPENINFERENCE_FRAMEWORK_EXPANSION_RESULTS.md), [`docs/OPENINFERENCE_FRAMEWORK_EXPANSION_TIER2_RESULTS.md`](https://github.com/JEONSEWON/Clew-by-Custos/blob/main/docs/OPENINFERENCE_FRAMEWORK_EXPANSION_TIER2_RESULTS.md).

### Registering your own tools

LangChain / CrewAI apps typically name their tools inside application code (`search_web`, `create_ticket`). Register them so waste is not stuck in `unclassified`:

```yaml
version: 1
tools:
  search_web:    { category: read_only }
  create_ticket: { category: side_effect, entity_id: response.ticket.id }
  run_python:    { category: payload_dependent }
  finalize:      { category: declarative }
```

Four categories, fail-fast validation, guardrails against advertising unmeasured paths. Details in [`docs/OPENINFERENCE_ADAPTER_PREREG.md`](https://github.com/JEONSEWON/Clew-by-Custos/blob/main/docs/OPENINFERENCE_ADAPTER_PREREG.md).

---

## Where it stands

### RedundancyBench (labeled ground truth)

Human-labeled benchmark ([arXiv:2605.29893](https://arxiv.org/abs/2605.29893)). Same `evaluate.py` imported directly from the paper's repo, all four redundancy categories:

| | Clew (deterministic) | Best method in the paper (LLM-as-judge) |
|---|---|---|
| Step-level F1 | **0.2642** | 0.2488 |
| Precision | 0.826 | n/a |
| Recall | 0.157 | n/a |

F1 0.2642 vs the paper's best LLM-as-judge 0.2488, with zero model calls. Recall 0.157 is by design: one pattern (`repeat` / `requery`), precisely. The rest is deliberately out of scope; see *What Clew doesn't do*.

Precision 0.826 may be a lower bound on Clew's file-level precision: of the 22 false-positive spans against the human labels, 21 were exact input-and-output repeats that no annotator labeled under any category, and 6 had zero state change in between. We do not claim all 22 are true waste; the label is genuinely ambiguous there.

### trace-commons (28 real Claude Code sessions)

Public dataset ([HF: trace-commons/agent-traces](https://huggingface.co/datasets/trace-commons/agent-traces)), full scan on 2026-07-19. **28 / 28** processed, **0 crashes**. **10 / 28** flagged (34 waste spans in the cascade output; 32 after the tool-error gate). Aggregate saving potential across the flagged sessions: **$1.01 to $10.12** (cache-hit lower to cache-miss upper). Per-session range: $0 (no waste) up to $0.64 to $6.40 (one 18-waste-span session).

*Cost estimation is Claude Code only, and is estimated saving potential, not measured cost.* The formula is `amp_tokens_i = waste_tokens_i × turns_after_i`, with `lower_i = amp_tokens × cache_read_price` and `upper_i = amp_tokens × base_input_price`. The wasted output is re-consumed as input on every subsequent turn; that is where the number comes from. Other adapters (OTel, OpenInference, Toolathlon) still detect waste but do not populate the cache-token fields the amplification calculator needs.

### Toolathlon (6,780 trajectories, cross-model scale)

Clew ran unmodified over Toolathlon (22 frontier models × 3 runs, [arXiv:2510.25726](https://arxiv.org/abs/2510.25726), CC-BY-4.0). 176,270 tool spans, 8,042 duplicate pairs. Excluding the `idempotent` grey area leaves **4,249 pairs (2.41% of tool spans)**, roughly **3× the rate seen on Claude Code sessions (0.80%)**. The Canvas hero above is one of these.

Duplicate creation check across the same corpus: **3,432 same-input side-effect pairs** scanned, **159 (4.63%) with differing entity IDs**, **76 (2.21%) with the same ID**, **3,197 (93.16%) without an extractable entity ID** (audit blind spot, not a verdict).

Toolathlon ships pass/fail labels, not step-level ground truth. Per-model rates vary 54× (0.157 to 8.463 candidate density per trajectory). "Model X wastes N× more than model Y" is not a claim we make; task-mix and success-rate confounds are uncontrolled.

---

## What Clew doesn't do

- **No fixes**, only diagnosis. The output is a report you read. Prompt changes, context caching, and tool routing are yours to make.
- **No real-time interception.** The `args-only` real-time gate was retired at precision 0.633 on labeled data (below the 0.70 threshold required for either auto-block or a confirm-prompt). Clew reads finished trace files, after the run.
- **No `reread` detector.** Retired at 3.3% precision on a 30-pair RedundancyBench sample: 29 of 30 same-path Read pairs were legitimate chunked reads at different `offset` / `limit` values. See [`docs/REREAD_DETECTOR_PREREG.md`](https://github.com/JEONSEWON/Clew-by-Custos/blob/main/docs/REREAD_DETECTOR_PREREG.md) §11.
- **No reasoning-level `pingpong`.** Code path exists but has fired only on synthetic traces. Blocked pending an external corpus that surfaces it, not killed.
- **Tool coverage is 26.4% on Toolathlon** (138 of 523 unique tool names). Unmapped tools drop into `unclassified` and reduce interval-scan tier precision. The banner shows coverage on your specific trace; `clew.yaml` closes the gap.
- **Cost is estimated saving potential, not measured.** Amplification formula assumes wasted output is re-consumed each subsequent turn (structural upper bound). Cache-hit lower to cache-miss upper; the exact split is not observable from vendor usage. Sonnet pricing assumed.
- **Toolathlon numbers are benchmark trajectories, not production sessions.** Scale evidence, not user data.
- **459 same-argument `emails-send_email` pairs on Toolathlon are not proven duplicates.** The tool does not return an entity ID, so `Duplicate creation check` cannot resolve them. They sit in the 3,197 `no_id` blind spot, surfaced but not claimed as a finding.
- **Semantic embedding does not carry the precision.** Same-topic real-world outputs do not cleanly separate in embedding space; the sha256 structural gate carries the precision result. We say so rather than imply the model is doing the work.

---

## How we keep ourselves honest

- **Pre-registration.** Every detection change is committed *before* results are run; predictions and stop-conditions are written first and not edited after.
- **Frozen parameters.** `φ`, `N`, and the embedding model are pinned to a git tag; changing them requires a documented recalibration, never a post-hoc nudge.
- **Published corrections.** Small-sample numbers that did not survive larger samples were retracted in the open (Toolathlon `1,343 → 1,195`, `4,251 → 4,249`; `"90% CI"` label corrected to `"95% two-sided"`). See [CHANGELOG.md](CHANGELOG.md).
- **Fixes driven by real data.** The trace-commons scan surfaced two adapter issues no synthetic test caught: session mid-run abort (3 / 28 crashes, recovered with `skip + warn`) and Anthropic `is_error: true` tool_result being sha256-identical (2 false positives across 269 error responses, gated at the report layer). See [`docs/CC_TRANSCRIPT.md`](https://github.com/JEONSEWON/Clew-by-Custos/blob/main/docs/CC_TRANSCRIPT.md) §29.

459 tests, CI on every PR, frozen parameters enforced as failing tests.

---

## Install

`[detect]` (default, lightweight; no torch): sha256 structural gate. Covers Claude Code, Toolathlon, RedundancyBench, and any OTel / OpenInference trace whose duplicated work sits at the tool layer. This is where every empirically validated detection so far comes from.

`[semantic]` (optional, ~2 GB with CUDA torch): adds the cosine gate for non-tool spans. Required for LangGraph chain-node paraphrase duplication.

```bash
pip install "clew-custos[semantic]"
```

CPU-only torch on Linux:

```bash
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install "clew-custos[semantic]"
```

From source:

```bash
pip install "clew-custos[detect] @ git+https://github.com/JEONSEWON/Clew-by-Custos.git"
```

Requires Python `≥ 3.12`.

## Use

```bash
python -m clew analyze path/to/trace.jsonl --out report.md
```

- Input: any auto-detected format from the table above.
- `--out` writes Markdown; `--json` writes structured output; `--no-snippets` omits output excerpts.
- Exit `0` whether or not waste is found; `1` on missing file, schema error, or missing detect dependencies.

Your Claude Code transcripts are at `~/.claude/projects/<slug>/<uuid>.jsonl`.

---

## License

MIT. Built under **Custos**.

External datasets referenced here (Toolathlon CC-BY-4.0, RedundancyBench MIT, trace-commons per its HF card) are analyzed locally and never redistributed.
