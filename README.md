# Clew

**Find where your coding agent wastes work — which file, which turn, why.**

```bash
pip install "clew-custos[detect]"   # published as clew-custos, not clew
python -m clew analyze ~/.claude/projects/<slug>/<uuid>.jsonl --out report.md
```

> Package name is **`clew-custos`** (the bare name `clew` on PyPI is an unrelated placeholder). The module still imports as `clew`.

Ran on 6,780 public benchmark traces: 8,042 duplicate calls detected — including 459 same-argument email sends. (Detection, not confirmed impact.)

Real excerpt from a public Claude Code session (`09d9abe9`, 258 turns; local path abbreviated, numbers unchanged):

```
Result: WASTE DETECTED

- wasted spans: 1
- category breakdown: 0 error_repeat, 0 side_effect, 1 idempotent, 0 unclassified
- Redundant-invocation candidates: 1 idempotent pairs. No verdict is rendered — refer to context and judge whether each was intentional.
  - idempotent 1 — 0 with no state change indicated, 0 with high tool volume, 1 with writes to other targets
    - indicated, by tool identity: declarative 0
    - indicated, by interval scan: no_side_effect 0; payload_dependent 0
    - writes to other targets: targeted_writes 1
      - Validated on Toolathlon: 28/30 hand-labeled TRUE (95% two-sided Clopper-Pearson lower ≈ 77.93%). Two write-then-revert observed.
  - Whether these were wasted invocations is a user judgment; the tool records only the observation.

### 1. [idempotent] requery — Read on `.../boot.ts`
- turns: turn 50 → re-run at turn 58 (of 258 total)
- state: No modification of this file in between — re-read output is unchanged.
- between_window: `targeted_writes` — State-changing tools were invoked in the interval, targeting other resources; this reread's output is unchanged from the first call.
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

### Waste categories

Each waste pair also carries a report-only category label with a short note on what that category typically points to. The label does **not** affect detection — the cascade output is unchanged; the label is layered on top of it for the reader.

- **`error_repeat`** — the response matches an error pattern (same call repeated after a failure). Usually the tool arguments are wrong and the agent re-runs with the same arguments without addressing the error message.
- **`side_effect`** — a state-changing tool (`Edit`, `Write`, `github-create_pull_request`, …) was invoked twice with the same arguments. Beyond wasted tokens, real side effects may have occurred; the report flags this for review rather than confirming impact.
- **`idempotent`** — a read-only or declarative tool (`Read`, `filesystem-list_directory`, …) was called repeatedly. This assumes the tool has no side effect **based on the tool name**, not a runtime guarantee. Whether that assumption holds in your setup — and whether state truly did not change between the two calls — needs verification against your execution context.
- **`unclassified`** — the tool's effect depends on the payload (command text, code, query body). `Bash`, `PowerShell`, `local-python-execute`, `terminal-run_command`, and `bigquery_run_query` are kept here — the tool name alone cannot classify them, so we don't try. Human review needed.

The mapping is by **exact tool name**, never inferred from name substrings.

### Idempotent sub-classification (`between_window`)

Since v0.3.2, the `idempotent` category is split further into a 5-value `between_window` label — the report now tells you **which evidence supports** the "no state change between calls" claim, rather than lumping every idempotent re-run together.

Like the category labels, `between_window` is a report-only annotation — what gets flagged as waste is unchanged (verified bit-identical; see [`docs/GREYZONE_EXPANSION_PREREG.md`](docs/GREYZONE_EXPANSION_PREREG.md) §9.8).

The 5 values, grouped by evidence:

- **Grouped as "no state change indicated" in the report:**
  - **`declarative`** — the tool itself is declarative or idempotent by name (`local-claim_done`, `filesystem-create_directory`); repeating it is not a waste question. The interval between calls is not examined.
  - **`no_side_effect`** — no state-changing tool sits between the two calls. **Hand-labeled sample: 30/30 TRUE** (95% two-sided Clopper-Pearson lower bound ≈ 88.43%; see [`docs/GREYZONE_EXPANSION_PREREG.md`](docs/GREYZONE_EXPANSION_PREREG.md) §2.1).
  - **`payload_dependent`** — a payload-dependent tool sits between (`Bash`, `terminal-run_command`, `snowflake-write_query`, …); the tool cannot infer from name whether it changed state. **Hand-labeled sample: 30/30 TRUE** (same CI note).
- **Grouped as "high_volume" in the report:**
  - **`high_volume`** — a state-changing tool is present AND ≥ 20 tool spans lie between the calls. **Hand-labeled sample: 29/30 TRUE** (95% two-sided Clopper-Pearson lower bound ≈ 82.78%). One case was a same-target repeated write with unchanged content (a `.tex` file rewritten three times with the same sha256). Grouped separately from `targeted_writes` (28/30, 77.93% lower bound) — its evidence is stronger, so it renders in a higher tier. See [`docs/GREYZONE_B23_EXTENSION_PREREG.md`](docs/GREYZONE_B23_EXTENSION_PREREG.md).
- **Grouped as "writes to other targets" in the report:**
  - **`targeted_writes`** — a state-changing tool with a specific target is between the two calls. **Hand-labeled sample: 28/30 TRUE** (95% two-sided Clopper-Pearson lower bound ≈ 77.93%). Two cases were write-then-revert: a `.tex` file and a `.md` file each restored to origin content after intermediate modifications. Grouped separately from `no_side_effect` and `payload_dependent` (30/30 each, 88.43% lower bound) because the evidence strength differs — two of thirty sampled pairs were write-then-revert; neither of the other two categories showed any in their own 30-pair samples. See [`docs/GREYZONE_B21_EXTENSION_PREREG.md`](docs/GREYZONE_B21_EXTENSION_PREREG.md).

Aggregate on Toolathlon (3,791 idempotent pairs):
`declarative 1,226` / `no_side_effect 888` / `payload_dependent 405` / `targeted_writes 248` / `high_volume 1,024`.

Report shows three top-level tiers rendered as four aggregate lines (the `indicated` tier splits into `by tool identity` and `by interval scan` sub-lines), ordered by evidence strength (`indicated` 88.43% → `high_volume` 82.78% → `writes to other targets` 77.93%); the tool does not render a final waste verdict. Whether a given idempotent re-run was actually wasted remains your judgment given your execution context. Pre-registration, priority rule (V2), and reproduction evidence: [`docs/GREYZONE_EXPANSION_PREREG.md`](docs/GREYZONE_EXPANSION_PREREG.md). Per-tier extensions: [`docs/GREYZONE_B21_EXTENSION_PREREG.md`](docs/GREYZONE_B21_EXTENSION_PREREG.md) (`targeted_writes`), [`docs/GREYZONE_B23_EXTENSION_PREREG.md`](docs/GREYZONE_B23_EXTENSION_PREREG.md) (`high_volume`).

**Honest scope for Claude Code users:** on 28 real Claude Code sessions only **16 pairs land in `idempotent`, and 56% of those fall into `high_volume`** (long intervals between rereads push them past the ≥ 20 threshold). In practice this sub-classification's yield concentrates on multi-tool environments (Toolathlon-like); a single Claude Code session usually leaves most idempotent pairs in the `high_volume` tier. The 82.78% lower bound applies to the Toolathlon 30-pair hand-labeled sample, not to Claude Code sessions — cross-population inference is a separate measurement. Threshold-20 revisit reserved for a separate pre-registration.

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
- Aggregate saving potential (across all wasteful sessions): **\$1.01 ~ \$10.12** (cache-hit lower to cache-miss upper).
- Per-session range: \$0 (no waste) up to \$0.64 ~ \$6.40 (one session, 18 waste spans).

**Honest scope:** trace-commons has **no step-level ground truth** — the 34 spans are cascade-flagged candidates plus a state-change check per file, not labeled as waste by a human annotator. Precision lives on RedundancyBench; scale on real data lives here.

### Toolathlon — 6,780 trajectories, cross-model scale

Beyond labeled and real-user data, Clew ran unmodified over **Toolathlon** — 22 frontier models × 3 runs ([arXiv:2510.25726](https://arxiv.org/abs/2510.25726), CC-BY-4.0). On 6,780 trajectories with 176,270 tool spans, Clew flagged **8,042 duplicate pairs**.

Breaking those pairs down by the report-only category labels above:

- **47% are the `idempotent` grey area** — read-only or completion-declaration re-runs whose "is this really waste?" answer depends on whether the underlying state changed between calls. Excluding this grey area leaves **4,249 pairs (2.41% of tool spans)** — roughly **3× the rate seen on Claude Code sessions (0.80%)**.
- **1,195 pairs are `side_effect` — state-changing tools re-invoked with the same arguments**, including **459 duplicate email-send pairs**. This is a detection of duplicate invocations with matching arguments; whether a real side effect actually occurred is not confirmed by the trace.

Toolathlon is benchmark trajectories, not real user sessions. The Toolathlon adapter provides no token information, so no cost estimate is produced for these traces.

**Honest scope:** Toolathlon ships only pass/fail labels, not step-level ground truth. Candidate density varies 54× across models (0.157 – 8.463 per trajectory), but "model X wastes 54× more than model Y" would over-claim — no labels; task-mix and success-rate confounds uncontrolled.

---

## Cost estimation

Every wasted step in a Claude Code trace has a knock-on cost: the stale tool result stays in the trajectory and is **re-consumed as input on every subsequent turn**. Naive single-consumption math makes waste look trivial (~\$0.001); the real number is the wasted output *times the remaining turns*.[^cache]

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
- Clew reports **detected waste**, not intervention. Independent research on removing
  redundant trajectory content — e.g. AgentDiet[^agentdiet] — reports downstream
  savings in a different setup (21.1–35.9% total cost, 39.9–59.7% input tokens on two
  coding benchmarks); those are that paper's numbers, not Clew's, and are cited only
  to flag the detection→intervention gap that Clew's report leaves for the user.

[^cache]: Prompt-cache economics in long-horizon agent workloads — including the
41–80% cost reduction range from strategic cache placement — are measured empirically
in Lumer et al., *Don't Break the Cache*
([arXiv:2601.06007](https://arxiv.org/abs/2601.06007)). Those numbers describe optimal
caching, not Clew's estimator; Clew's `lower_i`–`upper_i` bracket assumes the wasted
output is re-consumed and prices it under the observed cache-hit vs cache-miss split.

[^agentdiet]: Xiao et al., *Reducing Cost of LLM Agents with Trajectory Reduction
(AgentDiet)*, [arXiv:2509.23586](https://arxiv.org/abs/2509.23586).

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

*Cursor and Codex sessions are not supported yet — their local formats are under evaluation.*

Because it ingests OpenTelemetry and OpenInference, it can read traces from Langfuse, Arize Phoenix, and any OTel-instrumented agent. *(OTLP protobuf-JSON is not yet supported; the error message points you to the SDK-JSON conversion.)*

---

## How we keep ourselves honest

This repo treats anti-self-deception as a working discipline, not a slogan:

- **Pre-registration.** Every detection change is committed *before* results are run, so the prediction carries an external timestamp. Predictions and stop-conditions are written first and not edited after seeing results.
- **Frozen parameters.** `phi`, `N`, and the embedding model are pinned to a git tag; changing them requires a documented recalibration, never a post-hoc nudge.
- **Published corrections.** When a small-sample number didn't survive a larger sample, we retracted it in the open. (An early "failed traces waste 2.6× more" held on 108 traces but collapsed across 7,116 — retracted. 18 of 22 models still show higher waste on failed traces, but no single multiplier holds.) The Toolathlon `side_effect` count was published as **1,343** in v0.3.0 — that number came from an earlier prototype classifier that included `terminal-run_command` and `local-python-execute` as side effects; the shipped `_enrich.py` treats those tools as `unclassified` (payload-dependent, effect not inferable from name), which produces **1,195**. Corrected here; `4,251` on the same line also adjusted to `4,249` for the same reason (2 additional pairs re-categorized as `idempotent`). The Clopper-Pearson lower bound for the 30/30 hand-labeled samples was printed as **"90% CI lower ≈ 88%"** — the value (88.43%) is correct but the label was wrong: it is the **95% two-sided** CI lower bound (2.5% each tail), not 90%. The direction was conservative (95% CI is wider), and this shipped convention is now standardized to "95% two-sided (2.5% each tail)" across all docs.
- **Fixes driven by real data.** The trace-commons scan surfaced two adapter issues that no synthetic test caught: session mid-run abort (3/28 crashes → recovered with `skip + warn`) and Anthropic `is_error: true` tool_result being sha256-identical (2 false-positives across 269 error responses → gated at the report layer, cascade unchanged). Both are recorded in `docs/CC_TRANSCRIPT.md` §29.
- **Disclosed limits.** The semantic embedding layer does not cleanly separate same-topic real-world outputs — the `sha256` structural gate carries the precision result, not the embedding. We say so rather than imply the model is doing the work.

**253 tests**, CI on every PR, frozen parameters enforced as failing tests.

---

## Install

> **Note:** the bare name `clew` on PyPI is an unrelated placeholder — don't install that. This project is published as `clew-custos` (the module still imports as `clew`).

```bash
pip install "clew-custos[detect]"
```

**What `[detect]` covers vs. what `[semantic]` adds:**

- **`[detect]`** (default, lightweight — no torch): tool-call repeat / requery
  detection via the sha256 structural gate. Works on Claude Code JSONL, Toolathlon,
  RedundancyBench, and any OTel/OpenInference trace whose duplicated work sits at the
  tool layer. This is where every empirically validated detection so far comes from.
- **`[semantic]`** (optional, ~2 GB with CUDA torch): adds the cosine gate for
  non-tool spans (cos ≥ φ), required for LangGraph chain-node paraphrase duplication
  (same node running twice with reworded but semantically overlapping output). The
  pingpong code path also flows through this gate — see the honesty note above; it has
  fired only on synthetic traces so far.

```bash
pip install "clew-custos[semantic]"
```

On Linux, PyPI's default torch wheel pulls the CUDA stack (~2 GB). To use CPU-only
torch, install it first from the PyTorch CPU index:

```bash
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install "clew-custos[semantic]"
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
