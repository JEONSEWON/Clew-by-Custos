# Clew

**Find where your coding agent wastes work — which file, which turn, why.**

```bash
pip install "clew-custos[detect]"
python -m clew analyze ~/.claude/projects/<slug>/<uuid>.jsonl --out report.md
```

Real excerpt from a public Claude Code session (`09d9abe9`, 258 turns; local path abbreviated, numbers unchanged):

```
Result: WASTE DETECTED

### 1. requery — Read on `.../boot.ts`
- turns: turn 50 → re-run at turn 58 (of 258 total)
- state: No modification of this file in between — re-read output is unchanged.
- re-consumed across 200 subsequent turns (≈439 tokens/turn → 87800 amplification tokens)
- estimated cost impact: $0.026340 ~ $0.263400 (cache-hit to cache-miss)
```

Deterministic, no LLM in the loop. Every span in the session was `200 OK`; the trace stayed green. Clew reads the finished session and points at the redundant step.

---

## Why diagnosis (and not another dashboard)

Observability tools (Langfuse, Phoenix, LangSmith) **show you the trace**.
Clew **tells you which spans are waste, and why** — the exact file, the turns, whether the file was modified in between.

**Clew diagnoses; it does not fix.** The output is a report you read. What to change in your agent — prompt, context caching, tool routing — is a call only you can make.

Scope is deliberately narrow: **one working pattern (`repeat` / `requery`)**, done precisely. A second pattern for reasoning-level ping-pong (`pingpong`) is implemented but has not fired on any trace format we've validated (tool-span only) — we don't advertise what we haven't observed.

---

## How it works

A two-stage cascade, fully deterministic:

1. **Structural gate** — group steps by `(node, normalized input)`; a group with ≥ 2 occurrences is a candidate.
2. **Identity gate** — require `sha256(output_A) == sha256(output_B)`. If outputs differ (state changed, a retry succeeded where one failed), it is **not** flagged.

Frozen parameters (never hand-tuned): `phi = 0.514345`, `N = 2`, embedding model `paraphrase-multilingual-MiniLM-L12-v2`, pinned to a git tag with a manifest `sha256`. `N = 2` began as an arbitrary default; we later verified it is F1-optimal across `N ∈ {2, 3, 5, ∞}` on RedundancyBench (F1 decreases monotonically as N grows).

A report entry also carries a per-file state check — "no modification in between" vs "**File was modified in between** — may be a legitimate re-read" — so you can tell forced re-reads (waste) from legitimate ones. Tool-error responses (`is_error: true` in Anthropic tool_result) are excluded from waste with an explicit count in the report.

---

## Where it stands

### RedundancyBench — labeled ground truth

Human-labeled benchmark for redundant-step detection ([arXiv:2605.29893](https://arxiv.org/abs/2605.29893)):

| | Clew (deterministic) | Best method in the paper (LLM-as-judge) |
|---|---|---|
| **Step-level F1** | **0.2642** | 0.2488 |
| Precision | 0.826 | — |

Same `evaluate.py` (imported directly from their repo), same scope (all four redundancy categories). Clew surpasses the paper's best reported method **without a single model call**.

**Read this honestly — three caveats:**

1. **0.2488 is the paper's reported number, not something we re-ran.** The repo ships the scorer we import, but not the baseline's prediction files, so we can't reproduce 24.88% in our environment. The scorer is identical; the comparison point is **cited, not reproduced**.
2. **This is one benchmark.** A 0.0154 F1 margin on a single dataset is a signal, not a verdict. Recall is low (0.157) — Clew catches the one kind of waste it's built for and deliberately ignores the rest.
3. **Precision 0.826 may be a lower bound.** Of the 22 false-positive spans, 21 were exact input-and-output repeats that no annotator labeled under any category, and 6 had zero state change in between — i.e. redundancies the annotators appear to have missed. Owner review pending; we don't claim all 22 are waste.

### trace-commons — 28 real public Claude Code sessions

Public dataset ([trace-commons/agent-traces](https://huggingface.co/datasets/trace-commons/agent-traces)), full scan on 2026-07-19:

- **28 / 28** sessions processed, **0 crashes**.
- **10 / 28** flagged as wasteful (34 waste spans in the cascade output; 32 kept after the tool-error gate).
- Aggregate saving potential (across all wasteful sessions): **$1.01 ~ $10.12** (cache-hit lower to cache-miss upper).
- Per-session range: $0 (no waste) up to $0.64 ~ $6.40 (one session, 18 waste spans).

**Honest scope:** trace-commons has **no step-level ground truth** — the 34 spans are cascade-flagged candidates plus a state-change check per file, not annotator-verified waste. Precision lives on RedundancyBench; scale on real data lives here.

### Toolathlon — 7,116 trajectories, cross-model scale

Beyond labeled and real-user data, Clew ran unmodified over **Toolathlon** — 22 frontier models × 3 runs ([arXiv:2510.25726](https://arxiv.org/abs/2510.25726), CC-BY-4.0):

- **8,042 waste candidates** flagged across 176,270 tool spans, in 32 seconds.
- Candidate density varies **54× across models** (0.157 – 8.463 per trajectory).

**Honest scope:** Toolathlon ships only pass/fail labels, not step-level ground truth. These are **candidates**, not verified waste — "model X wastes 54× more than model Y" would over-claim (no labels; task-mix and success-rate confounds uncontrolled).

---

## Cost estimation

Every wasted step in a Claude Code trace has a knock-on cost: the stale tool result stays in the trajectory and is **re-consumed as input on every subsequent turn**. Naive single-consumption math makes waste look trivial (~$0.001); the real number is the wasted output *times the remaining turns*.

Formula per waste span:

```
amp_tokens_i  = waste_tokens_i × turns_after_i
lower_i (USD) = amp_tokens_i × cache_read_price  (fully cached re-consumption)
upper_i (USD) = amp_tokens_i × base_input_price  (uncached re-consumption)
```

Where `waste_tokens_i` comes directly from the vendor's `cache_creation_input_tokens` field on the assistant turn immediately after the waste, and `turns_after_i` is the number of assistant turns from the waste to the end of the session. Retry cascades where `prev.cache == next.cache` are filtered out with an explicit count.

**Read the estimate honestly:**

- It is **estimated saving potential, not measured cost.** The formula assumes the wasted output is re-consumed each subsequent turn (a structural upper bound).
- The range spans cache-hit (lower) to cache-miss (upper); the exact split is not observable from Anthropic usage.
- **Claude Code sessions only.** Other adapters (OTel, OpenInference, Toolathlon) still detect waste, but do not populate the cache-token fields the amplification calculator needs. Those reports show waste-detected without a dollar figure.
- Attribution assumes Sonnet 4.5 pricing.

---

## Reads your existing traces

Clew is a **complement, not a replacement.** It doesn't store or visualize traces — it reads what your observability stack already produces and points at the waste. It also runs standalone on raw session logs.

Auto-detected input formats:

| Source | Detected by |
|---|---|
| Claude Code session logs (`.jsonl`) | `sessionId` |
| OpenTelemetry SDK JSON | `context` |
| OpenInference (Phoenix / TRAIL lineage) | `span_id` / nested `child_spans` |
| Clew native trace JSON | `trace_id` + `spans` |
| Toolathlon trajectories | `modelname_run` + `task_status` |
| RedundancyBench | `tasks` + `simulations` |

Because it ingests OpenTelemetry and OpenInference, it can read traces from Langfuse, Arize Phoenix, and any OTel-instrumented agent. *(OTLP protobuf-JSON is not yet supported; the error message points you to the SDK-JSON conversion.)*

---

## How we keep ourselves honest

This repo treats anti-self-deception as a working discipline, not a slogan:

- **Pre-registration.** Every detection change is committed *before* results are run, so the prediction carries an external timestamp. Predictions and stop-conditions are written first and not edited after seeing results.
- **Frozen parameters.** `phi`, `N`, and the embedding model are pinned to a git tag; changing them requires a documented recalibration, never a post-hoc nudge.
- **Published corrections.** When a small-sample number didn't survive a larger sample, we retracted it in the open. (An early "failed traces waste 2.6× more" held on 108 traces but collapsed across 7,116 — retracted. 18 of 22 models still show higher waste on failed traces, but no single multiplier holds.)
- **Fixes driven by real data.** The trace-commons scan surfaced two adapter issues that no synthetic test caught: session mid-run abort (3/28 crashes → recovered with `skip + warn`) and Anthropic `is_error: true` tool_result being sha256-identical (2 false-positives across 269 error responses → gated at the report layer, cascade unchanged). Both are recorded in `docs/CC_TRANSCRIPT.md` §29.
- **Disclosed limits.** The semantic embedding layer does not cleanly separate same-topic real-world outputs — the `sha256` structural gate carries the precision result, not the embedding. We say so rather than imply the model is doing the work.

**239 tests**, CI on every PR, frozen parameters enforced as failing tests.

---

## Install

> **Note:** the bare name `clew` on PyPI is an unrelated placeholder — don't install that. This project is published as `clew-custos` (the module still imports as `clew`).

```bash
pip install "clew-custos[detect]"
```

Or from source:

```bash
pip install "clew-custos[detect] @ git+https://github.com/JEONSEWON/Clew-by-Custos.git"
```

Requires Python ≥ 3.12.

## Use

```bash
python -m clew analyze path/to/trace.jsonl --out report.md
```

- Input: any auto-detected format from the table above.
- `--out` writes Markdown; `--json` writes structured output; `--no-snippets` omits output excerpts.
- Exit `0` whether or not waste is found; `1` on missing file / schema error / missing detect dependencies.

For your own Claude Code sessions, transcripts live at `~/.claude/projects/<slug>/<uuid>.jsonl`.

---

## License

MIT. Built under **Custos**.

External datasets referenced here (Toolathlon CC-BY-4.0, RedundancyBench MIT, trace-commons per its HF card) are analyzed locally and never redistributed in this repo.
