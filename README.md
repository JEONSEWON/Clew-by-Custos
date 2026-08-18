# Boxdawn

<div align="center">

**Open source LLM observability for the waste axis no one else measures.**

[![PyPI](https://img.shields.io/pypi/v/boxdawn)](https://pypi.org/project/boxdawn/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python](https://img.shields.io/badge/python-%E2%89%A53.12-blue)](https://www.python.org/)
[![Tests](https://img.shields.io/badge/tests-691%20passing-brightgreen)](https://github.com/boxdawn/boxdawn/tree/main/tests)
[![Corpora](https://img.shields.io/badge/corpora-3%20%C2%B7%2016%2C864%20sessions-blueviolet)](#-where-it-stands--measured-not-marketed)

</div>

Boxdawn observes what your agent **repeats, resends, re-reads, and re-creates** — the waste axis that Langfuse, Arize, LangSmith, Braintrust, and Helicone do not measure. Four deterministic detectors + an opt-in LLM-as-judge semantic check, applied to trace files your agent already writes. Zero instrumentation. Pre-registered, frozen parameters, honesty preface on every claim.

```bash
pip install "boxdawn[detect]"
boxdawn analyze <trace>.jsonl --out report.md
```

> PyPI package is `boxdawn`. Python still imports as `import clew` (internal namespace, kept for backward compatibility with existing configs).

---

## ✨ Core Features

- **Deterministic waste detectors (4)** — `repeat` (tool-call cascade), `context_resend` (input-side chunk resend), `redundant_read` (Read-tool duplicates with interval gating), `duplicate_creation` (creation-tool ID-bridge on 26 mapped tools).
- **Cross-corpus waste-rate metric** — `WR_char` (byte ratio), `WR_cost` (dollar ratio with cache-tier-aware pricing), `SDR@10` (share of sessions with meaningful waste). Union across detectors. See §Where it stands.
- **Opt-in LLM-as-Judge semantic duplicate** — Claude Haiku 4.5 judges chunk pairs the deterministic gate cannot separate (paraphrased re-sends, non-byte-identical tool responses). Hard cost cap per session.
- **Zero-instrumentation ingest** — reads Claude Code JSONL, OpenTelemetry SDK JSON, OpenInference (Phoenix / TRAIL), Toolathlon trajectories, RedundancyBench, and Exgentic Agent LLM Traces v2. No SDK, no code change in your agent.
- **Cost attribution with source-URL-pinned pricing** — per-model rates for Sonnet 4.5 / 4.6, Opus 4.7, Haiku 4.5, GPT-4o family, GPT-5 / 5.2 / mini / o-series, Gemini 1.5 / 2.5 / 3-pro-preview, Grok 4 / fast / code-fast, DeepSeek v3.2, GLM 4.6, Kimi K2-0905 / K2.5, MiniMax M2, Qwen 3 Coder. Every entry carries `Source: URL (verified YYYY-MM-DD)`.
- **Anti-hype rigor** — pre-registration on every detector change, frozen parameters enforced as failing tests, published corrections on retracted numbers, honesty preface on p-hacking risk. See §How we keep ourselves honest.

**Coming next (Beta · Q4 2026):** hosted web dashboard, live monitoring endpoints, alerts (Slack / webhook), history & time-series, CI PR auto-comment. See §Roadmap.

**No instrumentation. No SDK. No code changes.** Boxdawn reads trace files your agent already writes.

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
pip install "boxdawn[detect]"
# Toolathlon corpus (CC-BY-4.0): huggingface.co/datasets/tsinghua-mars-lab/toolathlon
boxdawn analyze grok-4_2.jsonl --out report.md
```

*(Yes, agents legitimately re-read files. That is why the cascade below has two gates: the structural group only becomes a flag when the state check confirms nothing changed between the two calls, and the tool output is byte-identical.)*

---

## Why the waste axis

Observability platforms (Langfuse, Arize, LangSmith, Braintrust, Helicone) capture, store, and visualize traces. None of them measure the waste axis: how much of the input bill is context you already sent, files you already read, entities you already created, or tool calls that got the exact same answer as before. That is where Boxdawn starts, and it is complementary to the trace layer — a Langfuse trace fed into Boxdawn produces a waste report Langfuse itself does not compute.

Scope is deterministic-first: four deterministic detectors used in the waste-rate metric (`repeat` / `requery`, `context_resend`, `redundant_read`, `duplicate_creation`), the `pingpong` code path (implemented but not yet observed on real traces), and one opt-in LLM-as-judge check for semantic duplicates. Each detector is pre-registered with a frozen spec before results are measured.

The current release is the analyzer CLI you install with pip. The **hosted dashboard, live monitoring, and alert layer** (Beta · Q4 2026) live in a separate repo and share the same detectors + waste-rate metric; see §Roadmap for the split.

---

## How it works

A two-stage cascade, fully deterministic. Every parameter is pinned to a git tag with a manifest sha256.

**Stage 1: structural gate.** Group steps by `(node, normalized input)`. A group with `N ≥ 2` occurrences is a candidate.

**Stage 2: identity gate.** Compare the two outputs.

- **Tool spans**: require `sha256(output_A) == sha256(output_B)`. Byte-identical. This is the precision-carrying gate.
- **Non-tool spans**: require cosine similarity `≥ φ` against a frozen embedding (`paraphrase-multilingual-MiniLM-L12-v2`).

**Why sha256 for tools.** We cannot see inside a tool. We do not know whether `Bash: ls` had side effects, or whether `send_email` actually reached anyone. So we judge by result. Same input, same byte output, no state change in the interval: the second call was redundant. If outputs differ (a retry succeeded where one failed, an in-memory counter advanced), the pair is **not** flagged.

**Reverse case: duplicate creation.** If two `notion-API-post-page` calls really did create two pages, the responses carry different entity IDs, so byte-identity fails and the waste detector correctly excludes them. The `Duplicate creation check` section scans that excluded pool separately, using per-tool entity-ID extraction (26 tools currently mapped, see [`docs/ID_BRIDGE_PRODUCTION_PREREG.md`](https://github.com/boxdawn/boxdawn/blob/main/docs/ID_BRIDGE_PRODUCTION_PREREG.md) §1.1). This is what surfaced the 13 Canvas uploads above.

**Frozen parameters** (never hand-tuned): `φ = 0.514345`, `N = 2`. `N = 2` began as an arbitrary default; a later grid on `N ∈ {2, 3, 5, ∞}` on RedundancyBench found F1 decreases monotonically as `N` grows. F1-optimal, not tuned.

**State check.** For tool-repeat pairs the report says either "no modification of this file in between" or "**File was modified in between**, may be a legitimate re-read". Tool-error responses (`is_error: true` in Anthropic `tool_result`) are excluded with an explicit count.

**Report categories** (labels only; detection is unchanged):

- **`error_repeat`**: same call after a failure, same arguments as before.
- **`side_effect`**: state-changing tool invoked twice with the same arguments.
- **`idempotent`**: read-only or declarative tool called repeatedly. Sub-classified into a 5-value evidence tier; see [`docs/GREYZONE_EXPANSION_PREREG.md`](https://github.com/boxdawn/boxdawn/blob/main/docs/GREYZONE_EXPANSION_PREREG.md).
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
| Boxdawn native trace JSON | `trace_id` + `spans` |
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

Full results and per-instrumentor path table: [`docs/OPENINFERENCE_FRAMEWORK_EXPANSION_RESULTS.md`](https://github.com/boxdawn/boxdawn/blob/main/docs/OPENINFERENCE_FRAMEWORK_EXPANSION_RESULTS.md), [`docs/OPENINFERENCE_FRAMEWORK_EXPANSION_TIER2_RESULTS.md`](https://github.com/boxdawn/boxdawn/blob/main/docs/OPENINFERENCE_FRAMEWORK_EXPANSION_TIER2_RESULTS.md).

### Framework real-workload validation (Task #9 Phase B)

Beyond fixture coverage above, the full pipeline (ingest → 4 deterministic detectors + opt-in LLM-judge) was executed against real workloads of 4 Tier 1 frameworks under a fixed FizzBuzz retry-loop scenario, all using `claude-sonnet-4-5`:

| Framework | Instrumentation | CR events | CR % of input | Verdict |
|---|---|---|---|---|
| Anthropic SDK (direct wrap) | Helper wrap | 9 | **43.9%** | ✅ PASS |
| LlamaIndex FunctionAgent | Official OI | 6 | **40.9%** | ✅ PASS |
| OpenAI Agents SDK | Official OI (LiteLLM → Claude) | 4 | **35.5%** | ✅ PASS |
| AutoGen AssistantAgent | Official OI v0.1.10 | 0 | — | ❌ EMPTY |

Pre-registered §3 threshold ≥ 3/4 PASS → **GO**. AutoGen's instrumentor emits agent/tool spans but not the underlying LLM span (framework limitation, not a detector defect — see §12.4 of the prereg). The `repeat` detector, Redundant Read, and LLM-judge returned 0 across all four frameworks — the FizzBuzz scenario (3-6 turns, no realized retries, no Read tool) does not stimulate those detectors by construction (§12.7). Total API cost: ~$0.099 of a $10 budget cap.

Pre-registration + results: [`docs/TASK9_FRAMEWORK_REAL_WORKLOAD_PREREG.md`](https://github.com/boxdawn/boxdawn/blob/main/docs/TASK9_FRAMEWORK_REAL_WORKLOAD_PREREG.md).

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

Four categories, fail-fast validation, guardrails against advertising unmeasured paths. Details in [`docs/OPENINFERENCE_ADAPTER_PREREG.md`](https://github.com/boxdawn/boxdawn/blob/main/docs/OPENINFERENCE_ADAPTER_PREREG.md).

---

## Where it stands

### RedundancyBench (labeled ground truth)

Human-labeled benchmark ([arXiv:2605.29893](https://arxiv.org/abs/2605.29893)). Same `evaluate.py` imported directly from the paper's repo, all four redundancy categories:

| | Boxdawn (deterministic) | Best method in the paper (LLM-as-judge) |
|---|---|---|
| Step-level F1 | **0.2642** | 0.2488 |
| Precision | 0.826 | n/a |
| Recall | 0.157 | n/a |

F1 0.2642 vs the paper's best LLM-as-judge 0.2488, with zero model calls. Recall 0.157 is by design: one pattern (`repeat` / `requery`), precisely. The rest is deliberately out of scope; see *What Boxdawn doesn't do*.

Precision 0.826 may be a lower bound on Boxdawn's file-level precision: of the 22 false-positive spans against the human labels, 21 were exact input-and-output repeats that no annotator labeled under any category, and 6 had zero state change in between. We do not claim all 22 are true waste; the label is genuinely ambiguous there.

### trace-commons (28 real Claude Code sessions)

Public dataset ([HF: trace-commons/agent-traces](https://huggingface.co/datasets/trace-commons/agent-traces)), full scan on 2026-07-19. **28 / 28** processed, **0 crashes**. **10 / 28** flagged (34 waste spans in the cascade output; 32 after the tool-error gate). Aggregate saving potential across the flagged sessions: **$1.01 to $10.12** (cache-hit lower to cache-miss upper). Per-session range: $0 (no waste) up to $0.64 to $6.40 (one 18-waste-span session).

*Cost estimation is Claude Code only, and is estimated saving potential, not measured cost.* The formula is `amp_tokens_i = waste_tokens_i × turns_after_i`, with `lower_i = amp_tokens × cache_read_price` and `upper_i = amp_tokens × base_input_price`. The wasted output is re-consumed as input on every subsequent turn; that is where the number comes from. Other adapters (OTel, OpenInference, Toolathlon) still detect waste but do not populate the cache-token fields the amplification calculator needs.

### Toolathlon (6,780 trajectories, cross-model scale)

Boxdawn ran unmodified over Toolathlon (22 frontier models × 3 runs, [arXiv:2510.25726](https://arxiv.org/abs/2510.25726), CC-BY-4.0). 176,270 tool spans, 8,042 duplicate pairs. Excluding the `idempotent` grey area leaves **4,249 pairs (2.41% of tool spans)**, roughly **3× the rate seen on Claude Code sessions (0.80%)**. The Canvas hero above is one of these.

Duplicate creation check across the same corpus: **3,432 same-input side-effect pairs** scanned, **159 (4.63%) with differing entity IDs**, **76 (2.21%) with the same ID**, **3,197 (93.16%) without an extractable entity ID** (audit blind spot, not a verdict).

Toolathlon ships pass/fail labels, not step-level ground truth. Per-model rates vary 54× (0.157 to 8.463 candidate density per trajectory). "Model X wastes N× more than model Y" is not a claim we make; task-mix and success-rate confounds are uncontrolled.

### Context Resend Detector — coding agent workloads

New in Tier 1. Measures the input-side cost of chunks (message-array elements) resent byte-exact across LLM calls within one trace. Deterministic (sha256 chunk hash + provider-reported input token counts).

Aggregate over the same trace-commons corpus (28 CC sessions, `data/hf_recon/trace_commons_paths.txt`, `random.Random(seed=42)` order):

- **`resent_cost / total_input_cost = 0.9851`** (98.5%)
- Per-trace ratios cluster at 98-99%; **95% bootstrap CI [0.9796, 0.9878]** (`n_boot=1000, seed=42`)
- Pre-registered §7 threshold `≥ 0.20` → **GO**

**Caching caveat.** Anthropic `cache_read_input_tokens` bills at ~10% of the input rate. The 98.5% *structural* resend corresponds to roughly **8-15% of effective billed input cost** for users with caching enabled. The detector reports the structural number honestly; the billed-cost proxy is a derived interpretation and requires a v2 cache-tier split to measure directly.

Pre-registration + honesty preface: [`docs/CONTEXT_RESEND_DETECTOR_PREREG.md`](https://github.com/boxdawn/boxdawn/blob/main/docs/CONTEXT_RESEND_DETECTOR_PREREG.md).

### Waste-rate metric — cross-corpus (Tier 1)

Union of the four deterministic detectors (`repeat`, `context_resend`, `redundant_read`, `duplicate_creation`) into three per-corpus metrics: `WR_char` (UTF-8 byte ratio), `WR_cost` (dollar ratio via existing cost attribution), `SDR@10` (share of sessions with `WR_char ≥ 0.10`). Spec: [`docs/WASTE_RATE_METRIC_PREREG.md`](https://github.com/boxdawn/boxdawn/blob/main/docs/WASTE_RATE_METRIC_PREREG.md). Toolathlon adapter amendment (2026-08-11): [`docs/WASTE_RATE_TOOLATHLON_ADAPTER_AMENDMENT_PREREG.md`](https://github.com/boxdawn/boxdawn/blob/main/docs/WASTE_RATE_TOOLATHLON_ADAPTER_AMENDMENT_PREREG.md).

| Corpus | Included | `union_wr_char` | `union_wr_cost` | `union_sdr_at_10` | 95% bootstrap CI on `wr_char` |
|---|---:|---:|---:|---:|---|
| A · trace-commons (28 CC sessions) | 28 / 28 | **0.9930** | **0.2903** | **0.9643** | [0.9892, 0.9944] |
| B · Toolathlon (6,780 non-coding trajectories, 22 frontier models) | 6,659 / 6,780 | **0.9342** | **0.9202** | **0.9908** | [0.9314, 0.9368] |
| C · Exgentic Agent LLM Traces v2 (10,056 sessions, 5 frontier models × 6 benchmarks, up to 3.7M tokens / session) | 10,056 / 10,056 | **0.9233** | **0.9397** | **0.9332** | per-session mean [0.7827, 0.7920] — union CI not computed, see [amendment §10.2](https://github.com/boxdawn/boxdawn/blob/main/docs/WASTE_RATE_EXGENTIC_ADAPTER_AMENDMENT_PREREG.md#102-aggregate-post-adapter) |

Corpus B `WR_cost = 0.9202` — the [Cost Table Toolathlon Expansion](https://github.com/boxdawn/boxdawn/blob/main/docs/COST_TABLE_TOOLATHLON_EXPANSION_PREREG.md) (2026-08-11) closed the 98.2% pricing gap first (bringing the raw scan to 0.9189), and the [union arithmetic amendment §14](https://github.com/boxdawn/boxdawn/blob/main/docs/WASTE_RATE_METRIC_PREREG.md#14-amendment--union_wr_cost-per-span-attribution-2026-08-15) (2026-08-15) restored `redundant_read`'s +0.0013 previously dropped by a span-metadata recomputation shortcut. 6,780 / 6,780 (100%) built trajectories priced, median `cost_ratio = 1.000` against Toolathlon's own provider-billed totals. Corpus B fidelity: 5,445 / 6,659 (81.8%) exact count-match against `agent_llm_requests`; the remaining 18.2% differ by exactly `+1` due to trajectories ending on a `role=tool` message (root-caused in amendment §10.2). Token sum invariant preserved on 100% of built traces.

**Amendment prediction verdict.** P1 `union_wr_char ∈ [0.85, 0.999]`: pass (0.9342). P2 `union_sdr_at_10 ∈ [0.85, 1.00]`: pass (0.9908). P3 `union_wr_cost ∈ [0.10, 0.50]`: **miss** (0.9189 — the band was calibrated on Corpus A's cache-tier-aware billing; Toolathlon's adapter §1.4 encodes uncached-only billing by pre-commitment, so `WR_cost` collapses toward `WR_char`. Category error in the prediction, not a metric defect. Documented in [Cost Table Expansion §8.7](https://github.com/boxdawn/boxdawn/blob/main/docs/COST_TABLE_TOOLATHLON_EXPANSION_PREREG.md); band and adapter unchanged). P4 `context_resend ≥ 95%` of union numerator: pass (99.76%). No prediction band was adjusted post-hoc.

**Reading the numbers honestly.** LLM APIs are stateless — every call must include the full conversation. Some resend is mechanically required. The `WR_char` column measures the total resend footprint; the `WR_cost` column measures the share of the bill *in each corpus's own cost regime*. **Corpus A 29%** — dollars leaked *after Anthropic prompt caching is applied* (CC JSONL populates `cache_read_input_tokens` accurately). **Corpus B 92%** — dollars leaked *if the caller does not use prompt caching* (Toolathlon adapter §1.4 pre-commits to uncached-only billing because the benchmark does not encode cache tier). The 63-percentage-point gap is the caching lever's leverage on the same Context Resend detector.

**Note on `union_wr_char` vs `Context Resend Detector 98.5%` above.** These are two different measurements. `Context Resend Detector 98.5%` is `resent_cost / total_input_cost` on 28 CC sessions, single-detector. `union_wr_char` is the union across all four Tier 1 detectors on the same 28 CC sessions (`0.9930`), plus the 6,780-trajectory Corpus B extension. Both numbers are correct for their respective definitions; they are not interchangeable.

### Redundant Read Detector — standalone

New in Tier 1, distinct from the retired v0.3.0 reread cascade integration (see *What Boxdawn doesn't do* below). Emits its own `RedundantReadResult` with per-event tokens/dollars, contributes a distinct entry in the unified cost summary, and works cross-adapter (Claude Code, OpenInference, Toolathlon). Gate: both spans are read-nature tools on the same normalized target, the interval contains no write to that target and no payload-opaque shell tool, and (when the parent structure is known) both spans share the same nearest-AGENT ancestor. Output-identity is a strengthening flag, not a requirement — the pair is `confirmed=True` when outputs are byte-identical.

Pre-registration: [`docs/REDUNDANT_READ_DETECTOR_PREREG.md`](https://github.com/boxdawn/boxdawn/blob/main/docs/REDUNDANT_READ_DETECTOR_PREREG.md).

### LLM-as-Judge Semantic Duplicate (opt-in)

Semantic-equivalence check on chunk pairs that already pass a Jaccard pre-filter (threshold `0.30`, max 50 judged pairs per session). Uses `claude-haiku-4-5` as judge. **Default OFF**; requires explicit opt-in per session with a hard cost cap.

Two data points from Go/No-go measurement on 5 CC sessions (`seed=42`, `data/hf_recon/trace_commons_paths.txt`), both retained:

| Measurement | Matches / Pairs | Ratio | Cost | Verdict |
|---|---|---|---|---|
| Pre-amendment (base spec) | 4 / 159 | 0.0252 | $0.131 | SHIP-AS-IS |
| Post-amendment v1 (n=5 CC) | 83 / 159 | **0.5220** | $0.133 | **GO** |

Amendment v1 changes: (1) response parser strips markdown code fences (all 159 base responses were fence-wrapped); (2) rubric explicitly ignores randomly-generated per-invocation identifiers (`tool_use_id`, etc.) as non-semantic. Both changes were made **after** seeing the 2.52% baseline; the amendment document's honesty preface acknowledges the p-hacking risk and retains both data points as a joint record.

**Scale expansion (Amendment v2 · 2026-08-11 → 2026-08-12).** The n=5 v1 headline was recomputed on **n=48 sessions** (28 CC + 20 Toolathlon, `seed=42`, ~12h, $2.58):

| Corpus | n | Matches / Pairs | Precision |
|---|---:|---|---:|
| CC | 28 | 571 / 1,178 | **0.4847** |
| Toolathlon | 20 | 96 / 924 | **0.1039** |
| Unified | 48 | 667 / 2,102 | **0.3173** |

Bootstrap 95% CI on unified precision: **[0.2311, 0.4103]** (`n_boot=1000, seed=42`).

**Headline correction.** The 52.20% figure was measured on n=5 CC and did not survive scale. The corrected number for pitch material is **31.7% unified** (n=48, CI [23.1%, 41.0%]) — or **48.5% CC-only** for the same-corpus comparison. The v1 GO judgment stands (0.317 remains well above the base prereg 5% GO threshold); v1 and v2 data points are retained together per the honesty preface.

**These are detector precision figures** — of judge-evaluated candidate pairs, how many were confirmed equivalent. They are **not** trace-level waste rates. A separate metric would be needed to answer "what fraction of input tokens are wasted by semantic duplicates".

Pre-registration: [`docs/LLM_JUDGE_SEMANTIC_DUPLICATE_PREREG.md`](https://github.com/boxdawn/boxdawn/blob/main/docs/LLM_JUDGE_SEMANTIC_DUPLICATE_PREREG.md); amendment v1: [`docs/LLM_JUDGE_AMENDMENT_v1.md`](https://github.com/boxdawn/boxdawn/blob/main/docs/LLM_JUDGE_AMENDMENT_v1.md); scale expansion (v2): [`docs/LLM_JUDGE_SCALE_EXPANSION_AMENDMENT_PREREG.md`](https://github.com/boxdawn/boxdawn/blob/main/docs/LLM_JUDGE_SCALE_EXPANSION_AMENDMENT_PREREG.md).

### Cost attribution (Tier 1 · unified summary)

Prior versions priced only Claude Sonnet 4.5. As of the Cost Attribution Completion prereg, pricing tables now cover Sonnet 4.5 / 4.6, Opus 4.7, Haiku 4.5, GPT-4o and GPT-4o mini, Gemini 1.5 Pro and 1.5 Flash — with 4-tier cache-aware rates where the provider exposes them. The report emits a unified `Total analyzed / Total waste / Waste ratio` block at the top, plus per-detector breakdown in dollars. Each pricing entry carries a source URL and ISO-8601 verification date.

Pre-registration: [`docs/COST_ATTRIBUTION_COMPLETION_PREREG.md`](https://github.com/boxdawn/boxdawn/blob/main/docs/COST_ATTRIBUTION_COMPLETION_PREREG.md).

---

## 🚀 Roadmap · hosted dashboard (Beta · Q4 2026)

The analyzer CLI in this repo is the deterministic core. The hosted layer will bring the same detectors and waste-rate metric to the browser:

- **Mode A · Try Boxdawn (anonymous)** — upload a trace file or connect a LangSmith / Langfuse API key. 30-second waste report in-browser. No account.
- **Mode B · Live monitoring (account)** — personal ingest endpoint. Real-time waste alerts. Per-session dashboard with history and time-series. Slack / webhook notifications. CI PR auto-comment on your GitHub repos.
- **Team collaboration (post-Beta)** — accounts, permissions, shared datasets.

**Stack:** Vercel Next.js (frontend) · Modal serverless Python (detector runtime, same code as this repo) · Supabase (Postgres + Auth + Storage) · Resend (email). Domain: `boxdawn.com`.

The hosted layer imports Langfuse / LangSmith traces natively — the analyzer stays framework-neutral.

---

## What Boxdawn doesn't do

- **No fixes**, only diagnosis. The output is a report you read. Prompt changes, context caching, and tool routing are yours to make.
- **No real-time interception.** The `args-only` real-time gate was retired at precision 0.633 on labeled data (below the 0.70 threshold required for either auto-block or a confirm-prompt). Boxdawn reads finished trace files, after the run.
- **The v0.3.0 in-cascade `reread` gate was retired** at 3.3% precision on a 30-pair RedundancyBench sample: 29 of 30 same-path Read pairs were legitimate chunked reads at different `offset` / `limit` values. See [`docs/REREAD_DETECTOR_PREREG.md`](https://github.com/boxdawn/boxdawn/blob/main/docs/REREAD_DETECTOR_PREREG.md) §11. The current standalone **Redundant Read Detector** (see *Where it stands* above) is a different approach: it requires interval-clean gating (no intervening write to the same target, no payload-opaque shell tool in the interval) before flagging, and emits per-event tokens/dollars rather than bundling into the cascade waste-cost line.
- **No reasoning-level `pingpong`.** Code path exists but has fired only on synthetic traces. Blocked pending an external corpus that surfaces it, not killed.
- **Tool coverage is 26.4% on Toolathlon** (138 of 523 unique tool names). Unmapped tools drop into `unclassified` and reduce interval-scan tier precision. The banner shows coverage on your specific trace; `clew.yaml` closes the gap (config file name kept for backward compatibility).
- **Cost is estimated saving potential, not measured.** Amplification formula assumes wasted output is re-consumed each subsequent turn (structural upper bound). Cache-hit lower to cache-miss upper; the exact split is not observable from vendor usage. Sonnet pricing assumed.
- **Toolathlon numbers are benchmark trajectories, not production sessions.** Scale evidence, not user data.
- **459 same-argument `emails-send_email` pairs on Toolathlon are not proven duplicates.** The tool does not return an entity ID, so `Duplicate creation check` cannot resolve them. They sit in the 3,197 `no_id` blind spot, surfaced but not claimed as a finding.
- **Semantic embedding does not carry the precision.** Same-topic real-world outputs do not cleanly separate in embedding space; the sha256 structural gate carries the precision result. We say so rather than imply the model is doing the work.

---

## How we keep ourselves honest

- **Pre-registration.** Every detection change is committed *before* results are run; predictions and stop-conditions are written first and not edited after.
- **Frozen parameters.** `φ`, `N`, and the embedding model are pinned to a git tag; changing them requires a documented recalibration, never a post-hoc nudge.
- **Published corrections.** Small-sample numbers that did not survive larger samples were retracted in the open (Toolathlon `1,343 → 1,195`, `4,251 → 4,249`; `"90% CI"` label corrected to `"95% two-sided"`; Corpus B `union_wr_cost 0.9189 → 0.9202` per [WASTE_RATE_METRIC_PREREG §14](https://github.com/boxdawn/boxdawn/blob/main/docs/WASTE_RATE_METRIC_PREREG.md#14-amendment--union_wr_cost-per-span-attribution-2026-08-15)). See [CHANGELOG.md](CHANGELOG.md).
- **Fixes driven by real data.** The trace-commons scan surfaced two adapter issues no synthetic test caught: session mid-run abort (3 / 28 crashes, recovered with `skip + warn`) and Anthropic `is_error: true` tool_result being sha256-identical (2 false positives across 269 error responses, gated at the report layer). See [`docs/CC_TRANSCRIPT.md`](https://github.com/boxdawn/boxdawn/blob/main/docs/CC_TRANSCRIPT.md) §29.

691 tests, CI on every PR, frozen parameters enforced as failing tests.

---

## Install

`[detect]` (default, lightweight; no torch): sha256 structural gate. Covers Claude Code, Toolathlon, RedundancyBench, and any OTel / OpenInference trace whose duplicated work sits at the tool layer. This is where every empirically validated detection so far comes from.

`[semantic]` (optional, ~2 GB with CUDA torch): adds the cosine gate for non-tool spans. Required for LangGraph chain-node paraphrase duplication.

```bash
pip install "boxdawn[semantic]"
```

CPU-only torch on Linux:

```bash
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install "boxdawn[semantic]"
```

From source:

```bash
pip install "boxdawn[detect] @ git+https://github.com/boxdawn/boxdawn.git"
```

Requires Python `≥ 3.12`.

## Use

```bash
boxdawn analyze path/to/trace.jsonl --out report.md
```

- Input: any auto-detected format from the table above.
- `--out` writes Markdown; `--json` writes structured output; `--no-snippets` omits output excerpts.
- Exit `0` whether or not waste is found; `1` on missing file, schema error, or missing detect dependencies.

Your Claude Code transcripts are at `~/.claude/projects/<slug>/<uuid>.jsonl`.

---

## License

MIT. Built by **Boxdawn**.

External datasets referenced here (Toolathlon CC-BY-4.0, RedundancyBench MIT, trace-commons per its HF card) are analyzed locally and never redistributed.
