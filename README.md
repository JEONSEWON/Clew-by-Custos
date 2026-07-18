# Clew

**Deterministic detection of wasted work in agent traces.**

When an agent re-reads a file it already read, re-runs a query whose answer hasn't changed, or re-fetches state that's byte-for-byte identical — your trace stays green (every span is `200 OK`) but tokens leak. Dashboards say healthy; the run was wasteful. Clew reads the finished trace and flags the redundant steps, with **no LLM in the loop**.

---

## Where it stands

On **RedundancyBench** — a human-labeled benchmark for redundant-step detection ([arXiv:2605.29893](https://arxiv.org/abs/2605.29893)) — Clew scores:

| | Clew (deterministic) | Best method in the paper (LLM-as-judge) |
|---|---|---|
| **Step-level F1** | **0.2642** | 0.2488 |
| Precision | 0.826 | — |

Same `evaluate.py` (imported directly from their repo), same scope (all four redundancy categories). Clew surpasses the paper's best reported method **without a single model call**.

**Read this honestly — three caveats:**

1. **0.2488 is the paper's reported number, not something we re-ran.** The repo ships the scorer we import, but not the baseline's prediction files, so we can't reproduce 24.88% in our environment. The scorer is identical; the comparison point is cited, not reproduced.
2. **This is one benchmark.** A 0.0154 F1 margin on a single dataset is a signal, not a verdict. Recall is low (0.157) — Clew catches the one kind of waste it's built for and deliberately ignores the rest (see [Scope](#scope)).
3. **Precision 0.826 may be a lower bound.** Of the 22 false-positive spans, 21 were exact input-and-output repeats that no annotator labeled under any category, and 6 had zero state change in between — i.e. redundancies the annotators appear to have missed. Owner review pending; we don't claim all 22 are waste.

We'd rather show you the caveats than inflate the number. That discipline is the point (see [How we keep ourselves honest](#how-we-keep-ourselves-honest)).

---

## What it does

Clew detects **byte-identical re-execution**: a step run again with the same input, producing output whose `sha256` matches an earlier step's — with no state change in between. Nothing changed, yet the work was redone.

Concretely, this covers cases like:
- Re-reading a file that wasn't modified since the last read.
- Re-issuing a tool call with identical arguments and getting the identical result back.
- Re-querying information already retrieved earlier in the same trace.

This is **one pattern, done precisely** — not a broad heuristic. The name for it internally is `repeat_node`.

### Scope

Clew targets *duplicated* work only. It does **not** flag exploratory steps, speculative retries, or "should the agent have called a tool at all" decisions. On RedundancyBench, exploratory steps are ~68% of the labels — Clew doesn't chase them, which is exactly why its recall on the full four-category benchmark is low by design. It does one thing and is honest about what it leaves alone.

*(A second detector for back-and-forth loops between reasoning steps, `pingpong`, is implemented but only fires on traces that expose reasoning-level spans. The trace formats we've validated against so far are tool-span only, so it hasn't fired in practice. We don't advertise what we haven't observed.)*

---

## How it works

A two-stage cascade, fully deterministic:

1. **Structural gate** — group steps by `(node, normalized input)`; a group with >= 2 occurrences becomes a candidate.
2. **Identity gate** — require `sha256(output_A) == sha256(output_B)`. If the outputs differ (state changed, a retry succeeded where one failed), it is **not** flagged.

Frozen parameters (never hand-tuned): `phi = 0.514345`, `N = 2`, embedding model `paraphrase-multilingual-MiniLM-L12-v2`, pinned to a git tag with a manifest `sha256`. `N = 2` began as an arbitrary default, but we later verified it is F1-optimal across `N in {2, 3, 5, inf}` on RedundancyBench (F1 decreases monotonically as N grows).

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

## Validated at scale

Beyond the labeled benchmark, Clew ran unmodified over **Toolathlon** — 22 frontier models x 3 runs, **7,116 real long-horizon tool-use trajectories** ([arXiv:2510.25726](https://arxiv.org/abs/2510.25726), CC-BY-4.0):

- **8,042 waste candidates** flagged across 176,270 tool spans, in 32 seconds.
- Candidate density varies **54x across models** (0.157 - 8.463 per trajectory).

**Honest scope:** Toolathlon ships only pass/fail labels, not step-level ground truth. These are **candidates**, not verified waste — the density spread is a real measurement, but "model X wastes 54x more than model Y" would over-claim (no labels; task-mix and success-rate confounds uncontrolled). Precision lives on RedundancyBench; scale and cross-model comparison live here.

---

## How we keep ourselves honest

This repo treats anti-self-deception as a working discipline, not a slogan:

- **Pre-registration.** Every detection change is committed *before* results are run, so the prediction carries an external timestamp. Predictions and stop-conditions are written first and not edited after seeing results.
- **Frozen parameters.** `phi`, `N`, and the embedding model are pinned to a git tag; changing them requires a documented recalibration, never a post-hoc nudge.
- **Published corrections.** When a small-sample number didn't survive a larger sample, we retracted it in the open. (An early "failed traces waste 2.6x more" held on 108 traces but collapsed across 7,116 — retracted. 18 of 22 models still show higher waste on failed traces, but no single multiplier holds.)
- **Disclosed limits.** The semantic embedding layer does not cleanly separate same-topic real-world outputs — the `sha256` structural gate carries the precision result, not the embedding. We say so rather than imply the model is doing the work.

**231 tests**, CI on every PR, frozen parameters enforced as failing tests.

---

## Cost estimation (on the roadmap, not claimed)

The report has slots for `estimated wasted tokens` and `estimated wasted cost` — but the adapters we've scanned with don't yet populate per-span token counts, so today those fields read `unknown`. We won't print a dollar figure we can't stand behind.

There's a deeper reason it isn't a one-liner: the true cost of a wasted step isn't the single call. A stale tool result stays in the trajectory and is **re-consumed as input on every subsequent turn** — the real waste is that redundant output *times the remaining turns*. Naive single-consumption math makes waste look trivial (~$0.001/trajectory); the honest number requires modeling that amplification. That's Phase 2.

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

## Use

```bash
python -m clew analyze path/to/trace.jsonl --out report.md
```

A run looks like this:
$ python -m clew analyze session.jsonl --out report.md
report written -> report.md

```markdown
# Clew Waste Report

- trace_id: 2502fe9a-...
- detector params: phi=0.514345, N=2, model=paraphrase-multilingual-MiniLM-L12-v2

## Result: WASTE DETECTED
- wasted spans: 1
- estimated wasted tokens: unknown
- estimated wasted cost: unknown

## Wasted Span Details
| origin_node | repeat_node | cosine | tokens (wasted) | cost (wasted) |
|-------------|-------------|--------|-----------------|---------------|
| ToolSearch  | ToolSearch  | 1.0000 | unknown         | unknown       |
```

- Input: any auto-detected format above (one trace file).
- `--out` writes Markdown; `--json` writes structured output; `--no-snippets` omits output excerpts.
- Exit `0` whether or not waste is found; `1` on missing file / schema error / missing detect dependencies.

---

## License

MIT. Built under **Custos**.

External datasets referenced here (Toolathlon CC-BY-4.0, RedundancyBench MIT) are analyzed locally and never redistributed in this repo.
