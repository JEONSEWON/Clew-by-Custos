# Clew

**Detect token-wasting patterns in AI agent traces — deterministically, without extra LLM calls.**

Clew analyzes execution traces from multi-agent and agentic AI systems and flags where tokens are being burned on redundant work: the same search repeated, the same page revisited, two agents ping-ponging without progress. It makes a deterministic judgment about *whether* a pattern is wasteful — it does not delegate that judgment to an LLM.

Built by Custos. MIT licensed.

## Why Clew

Existing agent-observability tools (LangSmith, Langfuse, Phoenix, and others) already show you per-node token costs and let you trace an agent's steps. They show you *what happened*.

Clew answers a different question: **which of those steps were wasted?** And it answers deterministically — the same trace always yields the same verdict, with no LLM-as-judge in the loop and no per-analysis API cost.

- **Deterministic** — no LLM calls during analysis; reproducible verdicts.
- **Framework-independent** — reads the OpenInference / OpenTelemetry standard.
- **Honest by design** — flags borderline cases for human review rather than pretending to be certain.

## What it detects (today)

Three waste patterns, judged structurally + semantically without an LLM:

- **repeat_node** — the same node/tool run again with no meaningful change in between.
- **pingpong** — two steps bouncing back and forth without progress.
- **requery_known** — re-searching or re-visiting something already retrieved.

The core signal, validated across web-search and coding domains, is "same target, no substantive change."

## Install

Requires Python 3.12+.

    pip install "clew[detect]"

Or from source:

    pip install "git+https://github.com/JEONSEWON/Clew-by-Custos.git#egg=clew[detect]"

The detect extra pulls in the semantic layer (sentence-transformers). The embedding model downloads automatically on first run — no Hugging Face token required.

## Usage

    clew analyze path/to/trace.json

Options: --out report.md (markdown report), --json out.json (JSON report), --no-snippets (exclude output_text snippets).

Clew auto-detects three trace formats: serialized Clew Trace JSON, OpenTelemetry SDK span.to_json() flat array (Format A), and OpenInference nested tree / TRAIL-Phoenix style (Format C).

## Current status

Clew is early and honest about it.

**Validated**
- Synthetic held-out evaluation: F1 = 0.857, FP = 0 (seed=42, single-shot, frozen parameters). The zero false-positive result comes from the structural layer only — the semantic layer's discriminative power on real data is not yet demonstrated.
- Real-trace ingestion verified on LangGraph (live probe) and TRAIL (o3-mini / Claude trajectories, arXiv:2511.10650 benchmark family).
- Reproducible: fixed parameters (phi=0.514345, N=2, paraphrase-multilingual-MiniLM-L12-v2), Python 3.12, LF-normalized artifacts — same verdict on any OS.

**Not yet claimed**
- No production users and no measured real-world savings yet.
- The semantic layer is not yet validated on real-world output distributions.
- The synthetic threshold has not yet been recalibrated against real production traces.

In short: the detection logic is validated on synthetic data; real-world detection and demand are not yet proven.

## Roadmap

- **Coding-agent session waste** — detecting token waste in coding-agent sessions (Claude Code and similar) is in active development. The same "same target, no substantive change" signal appears in coding traces (re-reading the same file range, re-running unchanged commands); an adapter is being built.
- **Real-data calibration** — recalibrating the threshold against real production output distributions.
- **Team cloud hosting** — an optional hosted layer for teams; the open-source core stays free and local.

## How it works

Two-stage cascade: a cheap structural layer finds candidate repeats/ping-pongs by trace topology, then a semantic layer compares outputs with cosine similarity over multilingual embeddings to filter candidates. Parameters are frozen (phi=0.514345, N=2) and never hand-tuned to fit a dataset. Evaluation is single-shot on held-out synthetic traces with leakage guards enforced as tests.

## License

MIT © Custos
