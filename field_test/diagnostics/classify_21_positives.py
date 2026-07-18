"""field_test/diagnostics/classify_21_positives.py

§22.10 게이트 통과 21건 전수 분류 (A 게이트 설계 근거).

규율:
- 정의/코드/게이트/φ/N/model 무수정. 측정만.
- transcript 커밋 금지. basename, 앞 40/80자.
- raw 출력. 결론 금지. 판정 라벨은 소유자.

Usage:
    python field_test/diagnostics/classify_21_positives.py
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import warnings
from datetime import timezone, timedelta
from pathlib import Path

PROJECTS_ROOT = Path.home() / ".claude/projects"
MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
REV = "e8f8c211226b894fcb81acc59f3b34ba3efd5f42"
CACHE_DIR = Path.home() / ".cache/clew/embeddings"
PHI = 0.514345
N = 2
KST = timezone(timedelta(hours=9))


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _mask(txt: str) -> str:
    if not isinstance(txt, str):
        return str(txt)
    txt = re.sub(r"[A-Za-z]:[\\/][^\"'\s]+[\\/]([^\\/\"'\s]+)", r"BASENAME(\1)", txt)
    txt = re.sub(r"(?:/[^/\"'\s]+)+/([^/\"'\s]+)", r"BASENAME(\1)", txt)
    return txt


def _target_basename(span) -> str | None:
    try:
        inp = json.loads(span.input_text)
    except Exception:
        return None
    fp = inp.get("file_path") or inp.get("path") or ""
    return Path(fp).name if fp else None


def _has_exitplanmode_in_input(span) -> bool:
    try:
        inp = json.loads(span.input_text)
    except Exception:
        return False
    q = inp.get("query") or ""
    return "ExitPlanMode" in q


def _edits_between(trace, o_start, c_start, target_basename: str | None) -> int:
    if not target_basename:
        return 0
    ordered = sorted(trace.spans, key=lambda s: s.start_time)
    count = 0
    for e in ordered:
        if not (o_start < e.start_time < c_start):
            continue
        if e.agent_or_node_id not in ("Edit", "Write", "MultiEdit"):
            continue
        try:
            inp = json.loads(e.input_text)
        except Exception:
            continue
        fp = inp.get("file_path") or inp.get("path") or ""
        if Path(fp).name == target_basename:
            count += 1
    return count


def _load_entries(path: Path):
    entries = []
    with path.open(encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            s = line.strip()
            if not s:
                continue
            try:
                entries.append((lineno, json.loads(s)))
            except Exception:
                continue
    return entries


def _find_line_for_span(entries, span_id: str):
    for lineno, d in entries:
        msg = d.get("message")
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("id") == span_id:
                return lineno
    return None


def _window_compact_flag(entries, o_ln: int, c_ln: int) -> bool:
    for ln, d in entries:
        if not (o_ln < ln < c_ln):
            continue
        if d.get("compactMetadata") is not None:
            return True
        if d.get("isCompactSummary") is True:
            return True
    return False


def _window_user_count(entries, o_ln: int, c_ln: int) -> int:
    n = 0
    for ln, d in entries:
        if not (o_ln < ln < c_ln):
            continue
        if d.get("type") != "user":
            continue
        if d.get("isCompactSummary") is True:
            continue
        msg = d.get("message")
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        text_parts = []
        if isinstance(content, str):
            text_parts.append(content)
        elif isinstance(content, list):
            for b in content:
                if isinstance(b, dict) and b.get("type") == "text":
                    text_parts.append(b.get("text", ""))
        if "\n".join(text_parts).strip():
            n += 1
    return n


def _prev_user_head40(entries, c_ln: int) -> str:
    prev_text = ""
    for ln, d in entries:
        if ln >= c_ln:
            break
        if d.get("type") != "user":
            continue
        if d.get("isCompactSummary") is True:
            continue
        msg = d.get("message")
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        text_parts = []
        if isinstance(content, str):
            text_parts.append(content)
        elif isinstance(content, list):
            for b in content:
                if isinstance(b, dict) and b.get("type") == "text":
                    text_parts.append(b.get("text", ""))
        text = "\n".join(text_parts).strip()
        if text:
            prev_text = text
    if not prev_text:
        return ""
    flat = prev_text.replace("\n", " ").replace("\r", " ")
    return _mask(flat)[:40]


def _ingest(path: Path):
    from clew.ingest.claude_code import ingest_claude_code_jsonl
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            return ingest_claude_code_jsonl(path)
        except Exception:
            return None


def main() -> None:
    from clew.detect.structural import find_candidates
    from clew.detect.cascade import cascade
    from clew.detect.semantic import Embedder

    t0 = time.perf_counter()

    embedder = Embedder(model_name=MODEL, revision=REV, cache_dir=CACHE_DIR)

    sessions = sorted(PROJECTS_ROOT.glob("*/*.jsonl"))
    rows = []
    for p in sessions:
        trace = _ingest(p)
        if trace is None:
            continue
        cands = find_candidates(trace, N)
        res = cascade(trace, embedder, N, PHI)
        waste_ids = set(res.waste_span_ids)
        if not waste_ids:
            continue
        entries = _load_entries(p)
        session_short = p.stem[:8]
        idx = 0
        for o, c in cands:
            if c.span_id not in waste_ids:
                continue
            idx += 1
            tgt = _target_basename(c)
            edits = _edits_between(trace, o.start_time, c.start_time, tgt)
            gap = (c.start_time - o.start_time).total_seconds()
            oh = _sha256(o.output_text)
            ch = _sha256(c.output_text)
            o_ln = _find_line_for_span(entries, o.span_id)
            c_ln = _find_line_for_span(entries, c.span_id)
            compact_y = False
            user_cnt = 0
            prev40 = ""
            if o_ln and c_ln:
                compact_y = _window_compact_flag(entries, o_ln, c_ln)
                user_cnt = _window_user_count(entries, o_ln, c_ln)
                prev40 = _prev_user_head40(entries, c_ln)
            exitplan = _has_exitplanmode_in_input(c) if c.agent_or_node_id == "ToolSearch" else False
            rows.append({
                "session8": session_short,
                "idx": idx,
                "agent": c.agent_or_node_id,
                "target": tgt or "(None)",
                "gap": gap,
                "sha256eq": (oh == ch),
                "edits": edits,
                "compact": compact_y,
                "user_cnt": user_cnt,
                "prev40": prev40,
                "exitplan_ts": exitplan,
            })

    # --- 21행 표 ---
    print("=" * 118)
    print(f"§22.10 게이트 통과 waste 전수 분류 (총 {len(rows)}건)")
    print("=" * 118)
    hdr = (f"  {'session8':<10} {'#':>2}  {'agent':<12} {'target(basename)':<28} "
           f"{'gap(s)':>10} {'sha':>3} {'edt':>3} {'cmp':>3} {'usr':>3}  prev_user[:40]")
    print(hdr)
    print(f"  {'-'*10} {'-'*2}  {'-'*12} {'-'*28} {'-'*10} {'-'*3} {'-'*3} {'-'*3} {'-'*3}  {'-'*40}")
    for r in rows:
        tgt = r["target"]
        if len(tgt) > 28:
            tgt = tgt[:25] + "..."
        sha = "Y" if r["sha256eq"] else "N"
        cmp_ = "Y" if r["compact"] else "N"
        print(f"  {r['session8']:<10} {r['idx']:>2}  {r['agent']:<12} {tgt:<28} "
              f"{r['gap']:>10.1f} {sha:>3} {r['edits']:>3} {cmp_:>3} {r['user_cnt']:>3}  {r['prev40']!r}")

    # --- 집계 ---
    print()
    print("=" * 78)
    print("집계 (3 범주)")
    print("=" * 78)
    n_total = len(rows)
    n_compact = sum(1 for r in rows if r["compact"])
    n_toolsearch_epm = sum(1 for r in rows if r["agent"] == "ToolSearch" and r["exitplan_ts"])
    n_strong = sum(
        1 for r in rows
        if not r["compact"] and r["user_cnt"] == 0 and r["agent"] != "ToolSearch"
    )
    print(f"  전체                                                    : {n_total}")
    print(f"  compact_in_win==Y                                       : {n_compact}")
    print(f"  agent==ToolSearch AND input ExitPlanMode                : {n_toolsearch_epm}")
    print(f"  compact==N AND user_in_win==0 AND ToolSearch 아님         : {n_strong}")
    print(f"  세 범주 합 (중복 무시 단순 합)                            : {n_compact + n_toolsearch_epm + n_strong}")

    # 나머지 (세 범주 어디에도 안 들어간 건)
    def _cat(r):
        cats = []
        if r["compact"]:
            cats.append("compact")
        if r["agent"] == "ToolSearch" and r["exitplan_ts"]:
            cats.append("ts_epm")
        if (not r["compact"]) and r["user_cnt"] == 0 and r["agent"] != "ToolSearch":
            cats.append("strong")
        return cats

    unclassified = [r for r in rows if not _cat(r)]
    print(f"  세 범주 모두 미해당 (나머지)                              : {len(unclassified)}")
    if unclassified:
        print("  [나머지 목록]")
        for r in unclassified:
            print(f"    - {r['session8']} #{r['idx']} agent={r['agent']} target={r['target']!r} "
                  f"gap={r['gap']:.1f}s cmp={r['compact']} usr={r['user_cnt']} prev={r['prev40']!r}")

    # 중복 카테고리 (동일 row가 두 범주 이상)
    multi = [(r, _cat(r)) for r in rows if len(_cat(r)) >= 2]
    print(f"  두 범주 이상 겹침                                        : {len(multi)}")
    for r, cats in multi:
        print(f"    - {r['session8']} #{r['idx']} in {cats}")

    # --- ExitPlanMode 특수 집계 ---
    print()
    print("=" * 78)
    print("ExitPlanMode 특수 집계 (agent==ToolSearch AND input ExitPlanMode)")
    print("=" * 78)
    epm_rows = [r for r in rows if r["agent"] == "ToolSearch" and r["exitplan_ts"]]
    print(f"  건수                                                    : {len(epm_rows)}")
    if epm_rows:
        n_epm_compact = sum(1 for r in epm_rows if r["compact"])
        n_epm_user0 = sum(1 for r in epm_rows if r["user_cnt"] == 0)
        print(f"    그중 compact_in_win==Y                                : {n_epm_compact}")
        print(f"    그중 user_in_win==0                                   : {n_epm_user0}")
        print(f"    그중 compact==N AND user_in_win>=1                    : "
              f"{sum(1 for r in epm_rows if not r['compact'] and r['user_cnt'] >= 1)}")
        print("\n  [ExitPlanMode ToolSearch 개별]")
        for r in epm_rows:
            print(f"    - {r['session8']} #{r['idx']} gap={r['gap']:.1f}s "
                  f"cmp={r['compact']} usr={r['user_cnt']} prev={r['prev40']!r}")

    elapsed = time.perf_counter() - t0
    print()
    print("=" * 78)
    print(f"wall time: {elapsed:.1f}s")
    print("=" * 78)


if __name__ == "__main__":
    main()
