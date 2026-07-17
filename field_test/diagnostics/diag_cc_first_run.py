"""field_test/diagnostics/diag_cc_first_run.py

첫 실행 (2026-07-17, docs/CC_TRANSCRIPT.md §22.6) 결과 진단 스크립트.
§22.7 fold-back 근거를 생성한 명령들을 그대로 보존한다.

규율:
- transcript 자체는 레포에 커밋 금지 (~/.claude/projects/ 에서 읽기만).
- 경로는 basename 마스킹, output 은 앞 200~400자만.
- 대상 세션: `f96aee88-...` (§21 리콘과 동일 세션).

Usage:
    python field_test/diagnostics/diag_cc_first_run.py --q 1   # find_candidates 인용
    python field_test/diagnostics/diag_cc_first_run.py --q 2   # waste 3건 raw
    python field_test/diagnostics/diag_cc_first_run.py --q 3   # Edit/Write template
    python field_test/diagnostics/diag_cc_first_run.py --q 4   # Bash input
    python field_test/diagnostics/diag_cc_first_run.py --q 5   # Read input
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import warnings
from collections import Counter
from pathlib import Path

TARGET_JSONL = (
    Path.home()
    / ".claude/projects/C--Users-User-Desktop-Custos---clwe-project"
    / "f96aee88-df87-41a6-8f6e-be05d3928018.jsonl"
)
PHI = 0.514345
MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
REV = "e8f8c211226b894fcb81acc59f3b34ba3efd5f42"
CACHE_DIR = Path.home() / ".cache/clew/embeddings"


def _mask_path(txt: str) -> str:
    """Windows/POSIX 절대경로를 BASENAME(name) 으로 마스킹."""
    txt = re.sub(
        r"[A-Za-z]:[\\/][^\"\\\s]+[\\/]([^\\/\"]+)", r"BASENAME(\1)", txt
    )
    txt = re.sub(r"(?:/[^/\"\s]+)+/([^/\"]+)", r"BASENAME(\1)", txt)
    return txt


def _load_trace():
    from clew.ingest.claude_code import ingest_claude_code_jsonl

    warnings.simplefilter("ignore")
    return ingest_claude_code_jsonl(TARGET_JSONL)


def q1() -> None:
    """find_candidates 정의 확인 — repeat + pingpong 합집합인가."""
    p = Path("src/clew/detect/structural.py")
    text = p.read_text(encoding="utf-8")
    # find_candidates 함수 전문
    m = re.search(
        r"def find_candidates\(.*?(?=\ndef |\Z)", text, re.DOTALL
    )
    print("--- src/clew/detect/structural.py::find_candidates ---")
    print(m.group(0) if m else "NOT FOUND")


def q2() -> None:
    """waste 3건 각각의 input/output raw (경로 마스킹)."""
    from clew.detect.semantic import Embedder, cosine
    from clew.detect.structural import find_candidates

    trace = _load_trace()
    emb = Embedder(model_name=MODEL, revision=REV, cache_dir=CACHE_DIR)

    seen: set[str] = set()
    waste_details = []
    for origin, cand in find_candidates(trace, n=2):
        if cand.span_id in seen:
            continue
        seen.add(cand.span_id)
        s = cosine(emb.embed(origin.output_text), emb.embed(cand.output_text))
        if s >= PHI:
            waste_details.append((origin, cand, s))

    print(f"waste_pairs_count: {len(waste_details)}\n")
    for i, (o, c, s) in enumerate(waste_details, 1):
        print(f"=== waste #{i} : cosine={s:.4f} ===")
        print(f"  origin.name={o.agent_or_node_id}  cand.name={c.agent_or_node_id}")
        oi = _mask_path(o.input_text)[:400]
        ci = _mask_path(c.input_text)[:400]
        print(f"  origin.input_text ({len(o.input_text)}ch): {oi}")
        print(f"  cand.input_text   ({len(c.input_text)}ch): {ci}")
        print(f"  origin.output_text[0:200]: {_mask_path(o.output_text[:200])!r}")
        print(f"  cand.output_text[0:200]:   {_mask_path(c.output_text[:200])!r}")
        try:
            oj = json.loads(o.input_text)
            cj = json.loads(c.input_text)
            of = oj.get("file_path") or oj.get("path")
            cf = cj.get("file_path") or cj.get("path")
            if of and cf:
                same = Path(of).name == Path(cf).name
                print(f"  same_basename: {same}  (o={Path(of).name}, c={Path(cf).name})")
        except Exception:
            pass
        print()


def q3() -> None:
    """Edit/Write output_text 템플릿성 (distinct/total, top prefix)."""
    trace = _load_trace()
    for tool in ("Edit", "Write"):
        outs = [s.output_text for s in trace.spans if s.agent_or_node_id == tool]
        n = len(outs)
        if n == 0:
            print(f"--- {tool}: n=0 ---")
            continue
        distinct = len(set(outs))
        lens = [len(o) for o in outs]
        prefixes = Counter(o[:100] for o in outs)
        print(f"--- {tool} (n={n}) ---")
        print(f"  distinct_output_text: {distinct}/{n} ({distinct/n:.1%})")
        print(
            f"  len describe: min={min(lens)} median={int(statistics.median(lens))} "
            f"max={max(lens)} mean={int(statistics.mean(lens))}"
        )
        print(f"  top3_prefix (first 100ch, path 마스킹):")
        for pfx, cnt in prefixes.most_common(3):
            print(f"    [{cnt}x] {_mask_path(pfx)!r}")
        print()


def q4() -> None:
    """Bash input key-set 빈도 + command distinct + 재호출 카운트."""
    trace = _load_trace()
    bashes = [s for s in trace.spans if s.agent_or_node_id == "Bash"]
    inputs = [json.loads(s.input_text) for s in bashes]
    n = len(inputs)

    keysets = Counter(tuple(sorted(i.keys())) for i in inputs)
    print(f"Bash n={n}")
    print("input_key_sets (all):")
    for ks, c in keysets.most_common():
        print(f"  [{c}x] {ks}")

    descs = [i.get("description") for i in inputs if "description" in i]
    print(f"description_present: {len(descs)}/{n}, distinct: {len(set(descs))}")

    cmds = [i.get("command", "") for i in inputs]
    print(
        f"command_distinct: {len(set(cmds))}/{n} ({len(set(cmds)) / n:.1%})"
    )
    cmd_counts = Counter(cmds)
    reused = [(c, cnt) for c, cnt in cmd_counts.items() if cnt >= 2]
    print(
        f"command_reused: {len(reused)} distinct commands, "
        f"extra_calls={sum(cnt - 1 for _, cnt in reused)}"
    )
    print("top5_reused_commands (앞 60자, path 마스킹):")
    for c, cnt in cmd_counts.most_common(5):
        if cnt >= 2:
            print(f"  [{cnt}x] {_mask_path(c[:60])!r}")


def q5() -> None:
    """Read input key-set + file_path 재읽기 vs (path, offset, limit) 재읽기."""
    trace = _load_trace()
    reads = [s for s in trace.spans if s.agent_or_node_id == "Read"]
    inputs = [json.loads(s.input_text) for s in reads]
    n = len(inputs)

    keysets = Counter(tuple(sorted(i.keys())) for i in inputs)
    print(f"Read n={n}")
    print("input_key_sets (all):")
    for ks, c in keysets.most_common():
        print(f"  [{c}x] {ks}")

    paths = [Path(i.get("file_path", "")).name for i in inputs]
    path_counts = Counter(paths)
    extra_path = sum(cnt - 1 for cnt in path_counts.values() if cnt >= 2)
    print(f"file_path_distinct: {len(set(paths))}/{n}")
    print(f"file_path_reused_extra_calls: {extra_path}")

    tuples = [
        (Path(i.get("file_path", "")).name, i.get("offset"), i.get("limit"))
        for i in inputs
    ]
    tup_counts = Counter(tuples)
    extra_tuple = sum(cnt - 1 for cnt in tup_counts.values() if cnt >= 2)
    print(f"(file_path, offset, limit)_distinct: {len(set(tuples))}/{n}")
    print(f"(file_path, offset, limit)_reused_extra_calls: {extra_tuple}")

    inputs_str = [json.dumps(i, sort_keys=True) for i in inputs]
    inp_counts = Counter(inputs_str)
    extra_input = sum(cnt - 1 for cnt in inp_counts.values() if cnt >= 2)
    print(f"full_input_distinct: {len(set(inputs_str))}/{n}")
    print(f"full_input_reused_extra_calls: {extra_input}")

    print("\ntop5 재읽기 파일 (basename):")
    for p, cnt in path_counts.most_common(5):
        if cnt >= 2:
            print(f"  [{cnt}x] {p}")


HANDLERS = {"1": q1, "2": q2, "3": q3, "4": q4, "5": q5}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--q", required=True, choices=list(HANDLERS.keys()))
    args = ap.parse_args()
    if not TARGET_JSONL.exists():
        sys.exit(f"target session not found: {TARGET_JSONL}")
    HANDLERS[args.q]()


if __name__ == "__main__":
    main()
