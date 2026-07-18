"""field_test/diagnostics/diag_remaining5.py

§22.11.7 잔여 waste 5건 판정 재료 (진단, 커밋 금지).

규율:
- 정의/코드/게이트/φ/N/model 무수정. 측정만.
- transcript 커밋 금지. basename mask, 앞 80/200자.
- raw. 결론 금지. 판정 소유자.

대상:
  1) 2502fe9a  #1 ToolSearch (ExitPlanMode 검색)
  2) 8228879e  #1 ToolSearch (ExitPlanMode 검색)
  3) 8228879e  #2 Bash (no output)
  4) c848299d  #1 Read run_e3_diagnosis.py
  5) c848299d  #4 Bash (no output)

Usage:
    python field_test/diagnostics/diag_remaining5.py
"""
from __future__ import annotations

import json
import re
import warnings
from datetime import datetime
from pathlib import Path

PROJECTS_ROOT = Path.home() / ".claude/projects"
MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
REV = "e8f8c211226b894fcb81acc59f3b34ba3efd5f42"
CACHE_DIR = Path.home() / ".cache/clew/embeddings"
PHI = 0.514345
N = 2

TARGETS = [
    ("2502fe9a", "ToolSearch", "2026-07-06T13:37:08.010000+00:00", "case1 ExitPlanMode (2502fe9a #1)"),
    ("8228879e", "ToolSearch", "2026-07-10T08:48:07.443000+00:00", "case2 ExitPlanMode (8228879e #1)"),
    ("8228879e", "Bash",       "2026-07-10T09:06:25.720000+00:00", "case3 Bash (8228879e #2)"),
    ("c848299d", "Read",       "2026-07-12T07:47:24.045000+00:00", "case4 Read run_e3_diagnosis.py (c848299d #1)"),
    ("c848299d", "Bash",       "2026-07-12T09:40:27.651000+00:00", "case5 Bash (c848299d #4)"),
]


def _parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _mask(txt: str) -> str:
    if not isinstance(txt, str):
        return str(txt)
    txt = re.sub(r"[A-Za-z]:[\\/][^\"'\s]+[\\/]([^\\/\"'\s]+)", r"BASENAME(\1)", txt)
    txt = re.sub(r"(?:/[^/\"'\s]+)+/([^/\"'\s]+)", r"BASENAME(\1)", txt)
    return txt


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


def _ingest(path: Path):
    from clew.ingest.claude_code import ingest_claude_code_jsonl
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return ingest_claude_code_jsonl(path)


def _find_waste_pair(trace, embedder, target_agent: str, target_ts: str):
    """cascade + find_candidates 로직 그대로 → 지정된 cand 의 (origin, cand) 반환."""
    from clew.detect.structural import find_candidates
    from clew.detect.cascade import cascade
    res = cascade(trace, embedder, N, PHI)
    waste_ids = set(res.waste_span_ids)
    target_dt = _parse_ts(target_ts)
    seen: set[str] = set()
    for o, c in find_candidates(trace, N):
        if c.span_id in seen:
            continue
        if c.span_id not in waste_ids:
            continue
        seen.add(c.span_id)
        if c.agent_or_node_id == target_agent and c.start_time == target_dt:
            return o, c
    return None, None


def _list_user_turns_in_window(entries, o_ln, c_ln):
    out = []
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
        text = "\n".join(text_parts).strip()
        if not text:
            continue
        flat = _mask(text.replace("\n", " ").replace("\r", " "))
        out.append((ln, flat[:80]))
    return out


def _prev_user_before(entries, c_ln):
    prev = ""
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
            prev = text
    if not prev:
        return ""
    flat = _mask(prev.replace("\n", " ").replace("\r", " "))
    return flat[:200]


def _tool_uses_in_window(entries, o_ln, c_ln):
    """gap 창문 안 tool_use 목록: (lineno, name, input_masked head120)."""
    out = []
    for ln, d in entries:
        if not (o_ln < ln < c_ln):
            continue
        if d.get("type") != "assistant":
            continue
        msg = d.get("message")
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") != "tool_use":
                continue
            name = block.get("name", "")
            inp = block.get("input", {})
            inp_str = json.dumps(inp, ensure_ascii=False, sort_keys=True)
            flat = _mask(inp_str.replace("\n", " ").replace("\r", " "))
            out.append((ln, name, flat[:120]))
    return out


def _compact_in_window(entries, o_ln, c_ln):
    hits = []
    for ln, d in entries:
        if not (o_ln < ln < c_ln):
            continue
        if d.get("compactMetadata") is not None:
            hits.append((ln, "compactMetadata"))
        if d.get("isCompactSummary") is True:
            hits.append((ln, "isCompactSummary"))
    return hits


def _target_basename(span) -> str | None:
    try:
        inp = json.loads(span.input_text)
    except Exception:
        return None
    fp = inp.get("file_path") or inp.get("path") or ""
    return Path(fp).name if fp else None


def _find_session(prefix: str) -> Path | None:
    for p in sorted(PROJECTS_ROOT.glob("*/*.jsonl")):
        if p.stem.startswith(prefix):
            return p
    return None


def _pretty_input(input_text: str) -> str:
    """input_text 는 sort_keys JSON 문자열. mask 후 원본 반환."""
    return _mask(input_text)


def main() -> None:
    from clew.detect.semantic import Embedder
    embedder = Embedder(model_name=MODEL, revision=REV, cache_dir=CACHE_DIR)

    for prefix, agent, ts, label in TARGETS:
        p = _find_session(prefix)
        print()
        print("=" * 100)
        print(f"[{label}]")
        print("=" * 100)
        if p is None:
            print("  (session 없음)")
            continue
        print(f"  session file : {p.name}")

        trace = _ingest(p)
        entries = _load_entries(p)

        origin, cand = _find_waste_pair(trace, embedder, agent, ts)
        if origin is None:
            print("  (waste 쌍 찾지 못함)")
            continue

        o_ln = _find_line_for_span(entries, origin.span_id)
        c_ln = _find_line_for_span(entries, cand.span_id)
        gap = (cand.start_time - origin.start_time).total_seconds()

        print(f"  origin       : span_id={origin.span_id}  line={o_ln}  ts={origin.start_time.isoformat()}")
        print(f"  cand         : span_id={cand.span_id}  line={c_ln}  ts={cand.start_time.isoformat()}")
        print(f"  gap          : {gap:.1f}s")
        print(f"  target(base) : {_target_basename(cand) or '(None)'}")

        cflags = _compact_in_window(entries, o_ln, c_ln)
        print(f"  compact_in_window: {'Y' if cflags else 'N'}  hits={cflags}")

        print()
        print("  --- origin.input_text (mask 전문) ---")
        for line in _pretty_input(origin.input_text).splitlines() or [""]:
            print(f"    {line}")
        print("  --- cand.input_text (mask 전문) ---")
        for line in _pretty_input(cand.input_text).splitlines() or [""]:
            print(f"    {line}")

        print()
        print(f"  --- origin.output_text (len={len(origin.output_text)}) [:200] ---")
        print(f"    {origin.output_text[:200]!r}")
        print(f"  --- cand.output_text (len={len(cand.output_text)}) [:200] ---")
        print(f"    {cand.output_text[:200]!r}")

        print()
        print("  --- gap 창문 안 user turns (앞 80자, isCompactSummary 제외) ---")
        user_turns = _list_user_turns_in_window(entries, o_ln, c_ln)
        if not user_turns:
            print("    (없음)")
        else:
            print(f"    count={len(user_turns)}")
            for ln, head in user_turns:
                print(f"    line={ln}  {head!r}")

        print()
        prev = _prev_user_before(entries, c_ln)
        print("  --- cand 직전 마지막 user text (앞 200자) ---")
        print(f"    {prev!r}")

        print()
        print("  --- gap 창문 안 tool_use (name + input mask head 120자) ---")
        tools = _tool_uses_in_window(entries, o_ln, c_ln)
        if not tools:
            print("    (없음)")
        else:
            print(f"    count={len(tools)}")
            for ln, name, inp in tools:
                print(f"    line={ln}  {name:<15} {inp}")


if __name__ == "__main__":
    main()
