"""One-shot diagnostic: top-8 cosine progression (prog) pairs on the dev set.

Purpose (used when the stage-2 freeze was on hold):
- To separate two possible causes of a calibrate guard FAIL —
  (a) intrusions cluster on a specific pattern, vs
  (b) clean twins are too similar overall —
  spread the prog pairs in descending cosine order.
- No changes to the model or generators. Prints a table and exits.

Discipline:
- Never references the eval-set (seed=42) paths — only dev set (seed=7).
- Labels are used only for *classification* (dup vs prog); not used for
  detection or threshold decisions.
"""

from __future__ import annotations

import json
from pathlib import Path

from clew.detect.semantic import Embedder, cosine
from clew.detect.structural import find_candidates
from clew.model import Trace

DEV_TRACE_DIR = Path("eval/dev/seed-7/traces")
DEV_LABELS_PATH = Path("eval/dev/seed-7/labels.jsonl")
DEV_MANIFEST_PATH = Path("eval/dev/seed-7/set_manifest.json")

PRIMARY_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
N_FOR_PAIR_COLLECTION = 2  # same as calibrate.py
TOP_K = 8


def _resolve_revision(model_id: str) -> str:
    from huggingface_hub import HfApi

    return HfApi().model_info(model_id).sha


def _load_dev() -> tuple[list[Trace], dict[str, dict], dict[str, str]]:
    traces = [
        Trace.model_validate_json(p.read_text(encoding="utf-8"))
        for p in sorted(DEV_TRACE_DIR.glob("*.json"))
    ]
    labels: dict[str, dict] = {}
    with DEV_LABELS_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            labels[row["trace_id"]] = row
    manifest = json.loads(DEV_MANIFEST_PATH.read_text(encoding="utf-8"))
    # negative trace_id -> its paired pattern (from the pairs' `pattern` field in the manifest)
    neg_to_pattern: dict[str, str] = {}
    for pair in manifest["pairs"]:
        neg_to_pattern[pair["negative_trace_id"]] = pair["pattern"]
    return traces, labels, neg_to_pattern


def main() -> int:
    revision = _resolve_revision(PRIMARY_MODEL)
    embedder = Embedder(
        model_name=PRIMARY_MODEL, revision=revision, cache_dir=Path(".cache/embeddings")
    )
    traces, labels, neg_to_pattern = _load_dev()

    prog_rows: list[dict] = []  # each: {pattern, cos, origin_text, cand_text, trace_id, source}
    for trace in traces:
        lbl = labels[trace.trace_id]
        waste_ids = set(lbl["waste_span_ids"])
        is_positive = lbl["class"] == "positive"
        # Which pattern's clean twin does this trace belong to?
        if is_positive:
            pattern = lbl["pattern"]
            source = "positive(non-waste)"
        else:
            pattern = neg_to_pattern.get(trace.trace_id, "?")
            source = "clean"
        for origin, candidate in find_candidates(trace, n=N_FOR_PAIR_COLLECTION):
            is_dup = is_positive and candidate.span_id in waste_ids
            if is_dup:
                continue
            cos = cosine(
                embedder.embed(origin.output_text),
                embedder.embed(candidate.output_text),
            )
            prog_rows.append(
                {
                    "pattern": pattern,
                    "source": source,
                    "cos": cos,
                    "trace_id": trace.trace_id,
                    "origin_id": origin.span_id,
                    "cand_id": candidate.span_id,
                    "origin_text": origin.output_text,
                    "cand_text": candidate.output_text,
                }
            )

    prog_rows.sort(key=lambda r: r["cos"], reverse=True)
    top = prog_rows[:TOP_K]

    print(f"# top-{TOP_K} progression (prog) pair cosines on dev set")
    print(f"- model: {PRIMARY_MODEL} @ {revision}")
    print(f"- total prog pairs: {len(prog_rows)}")
    print()
    for i, r in enumerate(top, 1):
        print(f"## [{i}] cos = {r['cos']:.4f}")
        print(f"- pattern  : {r['pattern']}  ({r['source']})")
        print(f"- trace    : {r['trace_id']}  (origin={r['origin_id']}, candidate={r['cand_id']})")
        print(f"- origin   : {r['origin_text']!r}")
        print(f"- candidate: {r['cand_text']!r}")
        print()

    # Intrusions (cos ≥ φ=0.6515) — per-pattern count.
    PHI = 0.651453
    intruders = [r for r in prog_rows if r["cos"] >= PHI]
    print(f"# intrusions (cos ≥ φ={PHI}) among progression pairs")
    print(f"- total intrusions: {len(intruders)} / {len(prog_rows)} ({len(intruders)/len(prog_rows)*100:.1f}%)")
    from collections import Counter

    by_pattern = Counter((r["pattern"], r["source"]) for r in intruders)
    for (pat, src), c in by_pattern.most_common():
        print(f"  - {pat:14s} ({src:20s}): {c}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
