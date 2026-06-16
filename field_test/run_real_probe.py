"""field_test/run_real_probe.py — Real-trace probe orchestrator (SPEC §11).

Runs 5 LangGraph scenarios with real ChatAnthropic(Haiku) calls,
captures traces via capture_to_file(), runs cascade on each, measures
E3 non-waste cosine distributions, and writes REAL_PROBE_LOG.md.

Frozen params defined locally — never imported, never passed as CLI args.
API key read from ANTHROPIC_API_KEY env only — never written to any output.
"""
from __future__ import annotations

import os
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent))


def _check_api_key() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY not set. Export it before running.")
        sys.exit(1)


_check_api_key()  # before any import that might trigger LLM construction

from clew.capture import capture_to_file  # noqa: E402
from clew.detect.cascade import cascade, CascadeResult  # noqa: E402
from clew.detect.semantic import Embedder, cosine  # noqa: E402
from clew.model import Trace  # noqa: E402
import real_app  # noqa: E402

# ── Frozen params (immutable per SPEC §11) ─────────────────────────────────
PHI   = 0.514345
N     = 2
MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
REV   = "e8f8c211226b894fcb81acc59f3b34ba3efd5f42"
CACHE = Path(".cache/embeddings")
TOPIC = "quantum computing basics"

COST_TABLE = {"claude-haiku-4-5-20251001": 0.000001}  # $1/MTok input approximation

FIELD_DIR = Path(__file__).parent

# ── Scenario definitions ───────────────────────────────────────────────────

_SCENARIOS = [
    {
        "name":     "clean",
        "factory":  real_app.make_clean_app,
        "inputs":   {"topic": TOPIC, "research": "", "summary": "", "critique": ""},
        "out_path": FIELD_DIR / "real_clean.json",
        "expected": False,
        "note":     "E1: FP=0 기대",
    },
    {
        "name":     "repeat_node",
        "factory":  real_app.make_repeat_node_app,
        "inputs":   {"topic": TOPIC, "research": "", "loop_count": 0, "summary": "", "critique": ""},
        "out_path": FIELD_DIR / "real_repeat_node.json",
        "expected": True,
        "note":     "E2: llm repeat 탐지 기대 (입력 게이트 없음)",
    },
    {
        "name":     "requery_known",
        "factory":  real_app.make_requery_known_app,
        "inputs":   {"query": TOPIC, "result": "", "loop_count": 0, "summary": "", "critique": ""},
        "out_path": FIELD_DIR / "real_requery_known.json",
        "expected": True,
        "note":     "E2: tool 입력 게이트 경로 탐지 기대 (동일 입력)",
    },
    {
        "name":     "requery_clean",
        "factory":  real_app.make_requery_clean_app,
        "inputs":   {"query": TOPIC, "result": "", "loop_count": 0, "summary": "", "critique": ""},
        "out_path": FIELD_DIR / "real_requery_clean.json",
        "expected": False,
        "note":     "E2 음성 대조: tool 입력 게이트가 다른 입력 거절 → 미탐지 기대",
    },
    {
        "name":     "pingpong",
        "factory":  real_app.make_pingpong_app,
        "inputs":   {"topic": TOPIC, "research": "", "critique": "", "ping_count": 0},
        "out_path": FIELD_DIR / "real_pingpong.json",
        "expected": True,
        "note":     "E2: pingpong A→B→A→B 탐지 기대",
    },
]


# ── Core functions ─────────────────────────────────────────────────────────

def _run_scenario(
    scenario: dict,
    embedder: Embedder,
) -> tuple[Trace | None, CascadeResult | None, str | None]:
    try:
        import anthropic
        trace = capture_to_file(
            scenario["factory"](),
            scenario["inputs"],
            scenario["out_path"],
            cost_table=COST_TABLE,
        )
        cr = cascade(trace, embedder, n=N, phi=PHI)
        return trace, cr, None
    except anthropic.RateLimitError as e:
        return None, None, f"RateLimitError: {e}"
    except anthropic.APIStatusError as e:
        return None, None, f"APIStatusError {e.status_code}: {e.message}"
    except anthropic.APIConnectionError as e:
        return None, None, f"APIConnectionError: {e}"


def _e3_cosines(trace: Trace, cr: CascadeResult, embedder: Embedder) -> dict:
    waste_ids = set(cr.waste_span_ids)
    spans = [s for s in trace.spans if s.span_id not in waste_ids]
    pairs = []
    for i, a in enumerate(spans):
        for b in spans[i + 1:]:
            c = cosine(embedder.embed(a.output_text), embedder.embed(b.output_text))
            pairs.append((a.agent_or_node_id, b.agent_or_node_id, c))
    vals = [c for _, _, c in pairs]
    return {
        "pairs": pairs,
        "count": len(vals),
        "min": min(vals) if vals else None,
        "median": statistics.median(vals) if vals else None,
        "max": max(vals) if vals else None,
        "above_phi": sum(1 for v in vals if v >= PHI),
    }


# ── Log writer ─────────────────────────────────────────────────────────────

def _write_log(results: list[dict]) -> None:
    now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = [
        "# REAL_PROBE_LOG.md — Real-Trace Probe Results (SPEC §11)",
        "",
        f"Date: {now}",
        f"Frozen params: PHI={PHI}, N={N}, MODEL={MODEL}",
        f"Topic: {TOPIC!r}",
        "",
        "---",
        "",
        "## Per-Trace Results",
        "",
    ]

    e1_result: tuple[bool | None, bool] | None = None   # (detected, expected)
    e2_rows: list[tuple[str, bool | None, bool, bool | None]] = []

    for r in results:
        name     = r["name"]
        cr       = r.get("cr")
        expected = r["expected"]
        error    = r.get("error")
        e3       = r.get("e3")
        note     = r["note"]

        detected = cr.wasteful if cr is not None else None
        match    = (detected == expected) if detected is not None else None
        status   = "PASS" if match else ("FAIL" if match is not None else "ERROR")

        if name == "clean":
            e1_result = (detected, expected)
        else:
            e2_rows.append((name, detected, expected, match))

        lines += [
            f"### {name}",
            f"- note: {note}",
            f"- detected: {'Y' if detected else 'N' if detected is not None else 'ERROR'}",
            f"- expected: {'Y' if expected else 'N'}",
            f"- status: {status}",
        ]
        if cr is not None:
            lines += [
                f"- waste_span_ids: {cr.waste_span_ids or '[]'}",
                f"- waste_tokens: {cr.waste_tokens}",
                f"- waste_cost: {cr.waste_cost:.6f}",
            ]
        if error:
            lines.append(f"- error: {error}")

        if e3 and e3["count"] > 0:
            lines += [
                "",
                "#### E3 Non-Waste Span Cosines",
                "| Span A | Span B | cosine | ≥ φ? |",
                "|--------|--------|--------|------|",
            ]
            for a_id, b_id, c in e3["pairs"]:
                above = "Y" if c >= PHI else "N"
                lines.append(f"| {a_id} | {b_id} | {c:.4f} | {above} |")
            lines += [
                "",
                f"- count: {e3['count']}",
                f"- min: {e3['min']:.4f}",
                f"- median: {e3['median']:.4f}",
                f"- max: {e3['max']:.4f}",
                f"- above φ ({PHI}): {e3['above_phi']}/{e3['count']}",
            ]
        elif e3 is not None:
            lines.append("- E3: no non-waste pairs to measure")

        lines.append("")

    # ── Summary ────────────────────────────────────────────────────────────
    lines += [
        "---",
        "",
        "## Expectation Summary",
        "",
        "### E1 (clean → FP=0)",
    ]
    if e1_result is not None:
        det, exp = e1_result
        status = "PASS" if (det == exp) else "FAIL" if det is not None else "ERROR"
        lines.append(f"- detected={'Y' if det else 'N' if det is not None else 'ERROR'}, expected={'Y' if exp else 'N'} → {status}")
    else:
        lines.append("- not run")

    lines += ["", "### E2 (waste scenarios + negative control)"]
    for name, detected, expected, match in e2_rows:
        status = "PASS" if match else ("FAIL" if match is not None else "ERROR")
        det_str = "Y" if detected else ("N" if detected is not None else "ERROR")
        exp_str = "Y" if expected else "N"
        lines.append(f"- {name}: detected={det_str}, expected={exp_str} → {status}")

    lines += [
        "",
        "### E3 (non-waste cosine distribution vs finding3 0.48–0.57 cluster)",
        "See per-trace tables above.",
        "Finding3 predicts non-waste cosines cluster 0.48–0.57.",
        f"φ={PHI} is untouched regardless of distribution outcome.",
        "",
        "---",
        "",
        "## API Call Count",
        "- clean: 3 LLM calls",
        "- repeat_node: 4 LLM calls (researcher×2 + summarizer + critic)",
        "- requery_known: 2 LLM + 2 tool calls (searcher×2 same input + summarizer + critic)",
        "- requery_clean: 2 LLM + 2 tool calls (searcher×2 diff input + summarizer + critic)",
        "- pingpong: 4 LLM calls (researcher×2 + critic×2)",
        "- Total: 15 LLM calls + 4 deterministic tool calls",
    ]

    log_path = FIELD_DIR / "REAL_PROBE_LOG.md"
    log_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"[LOG] Written: {log_path}")


# ── Main ───────────────────────────────────────────────────────────────────

def main() -> None:
    print(f"[probe] PHI={PHI}, N={N}, MODEL={MODEL}")
    print(f"[probe] topic={TOPIC!r}")
    print()

    embedder = Embedder(model_name=MODEL, revision=REV, cache_dir=CACHE)

    results = []
    for scenario in _SCENARIOS:
        name = scenario["name"]
        print(f"[{name}] running...")
        trace, cr, error = _run_scenario(scenario, embedder)

        if error:
            print(f"[{name}] ERROR — {error}")
            sys.exit(1)

        e3 = _e3_cosines(trace, cr, embedder) if (trace and cr) is not None else None

        detected = cr.wasteful if cr is not None else None
        expected = scenario["expected"]
        match    = (detected == expected) if detected is not None else None
        status   = "PASS" if match else "FAIL"
        print(f"[{name}] detected={detected}, expected={expected} → {status} | tokens={cr.waste_tokens if cr else 'n/a'}")

        results.append({
            "name":     name,
            "cr":       cr,
            "expected": expected,
            "note":     scenario["note"],
            "error":    error,
            "e3":       e3,
        })

    print()
    _write_log(results)
    print("[probe] done.")


if __name__ == "__main__":
    main()
