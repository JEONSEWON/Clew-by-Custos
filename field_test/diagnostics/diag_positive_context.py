"""field_test/diagnostics/diag_positive_context.py

참양성 판정 재료 (진단). §22.10 게이트 통과 21건 중 4개 깨끗한 세션 상세 + 자기 세션(07f97584) 요약표.

규율:
- 정의/코드/게이트 무수정. 진단.
- transcript 커밋 금지. path basename, code 앞 80자.
- raw. 결론 금지. 판정은 세션 소유자.

Usage:
    python field_test/diagnostics/diag_positive_context.py                # 4 세션 + F 표
    python field_test/diagnostics/diag_positive_context.py --only 2502fe9a
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import warnings
from datetime import timezone, timedelta, datetime
from pathlib import Path

PROJECTS_ROOT = Path.home() / ".claude/projects"
CUSTOS_SLUG = "C--Users-User-Desktop-Custos---clwe-project"
KST = timezone(timedelta(hours=9))

MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
REV = "e8f8c211226b894fcb81acc59f3b34ba3efd5f42"
CACHE_DIR = Path.home() / ".cache/clew/embeddings"
PHI = 0.514345
N = 2

TARGET_SESSIONS = [
    "2502fe9a-a030-4dad-912b-37eb7e8403db.jsonl",
    "8228879e-0587-4e59-a8b4-b75b9ab2cd6a.jsonl",
    "c848299d-b6aa-47b2-9ef7-4cb1718089a9.jsonl",
    "72015129-cd97-4591-9a1c-31fc447e38a2.jsonl",
]
SELF_SESSION = "07f97584-1ff7-4f46-a171-d8e7404ac747.jsonl"


def _mask(txt: str) -> str:
    if not isinstance(txt, str):
        return str(txt)
    # Windows path → basename
    txt = re.sub(r"[A-Za-z]:[\\/][^\"'\s]+[\\/]([^\\/\"'\s]+)", r"BASENAME(\1)", txt)
    # Unix path → basename
    txt = re.sub(r"(?:/[^/\"'\s]+)+/([^/\"'\s]+)", r"BASENAME(\1)", txt)
    return txt


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _target_basename(span) -> str | None:
    try:
        inp = json.loads(span.input_text)
    except Exception:
        return None
    fp = inp.get("file_path") or inp.get("path") or ""
    return Path(fp).name if fp else None


def _fmt_ts_kst(dt: datetime) -> str:
    kst = dt.astimezone(KST)
    return kst.isoformat()


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


def _parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _find_lines_for_span(entries, span_id: str):
    """(use_lineno, use_ts_str, tool_use_block) 반환. tool_result 없이."""
    use = None
    for lineno, d in entries:
        msg = d.get("message")
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use" and block.get("id") == span_id:
                use = (lineno, d.get("timestamp"), block)
                break
    return use


def _window_lines(entries, o_ln: int, c_ln: int):
    return [(ln, d) for ln, d in entries if o_ln < ln < c_ln]


def _window_tool_uses(window):
    out = []
    for ln, d in window:
        if d.get("type") != "assistant":
            continue
        msg = d.get("message")
        if not isinstance(msg, dict):
            continue
        for block in msg.get("content", []):
            if isinstance(block, dict) and block.get("type") == "tool_use":
                inp = block.get("input", {}) or {}
                s = _mask(json.dumps(inp, ensure_ascii=False))[:80]
                out.append((ln, block.get("name"), block.get("id"), s, inp))
    return out


def _window_type_value_counts(window):
    cnt: dict[str, int] = {}
    for ln, d in window:
        t = d.get("type", "<none>")
        cnt[t] = cnt.get(t, 0) + 1
    return dict(sorted(cnt.items(), key=lambda kv: (-kv[1], kv[0])))


def _window_compact_markers(window):
    hits = []
    for ln, d in window:
        cm = d.get("compactMetadata")
        if cm is not None:
            hits.append((ln, d.get("type"), "compactMetadata", str(cm)[:120]))
        if d.get("isCompactSummary") is True:
            hits.append((ln, d.get("type"), "isCompactSummary", "True"))
    return hits


def _window_user_turns(window):
    out = []
    for ln, d in window:
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
            out.append((ln, text))
    return out


def _prev_user_turn(entries, c_ln: int):
    prev = None
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
            prev = (ln, text)
    return prev


def _state_change_hits(tool_uses, target_basename: str | None):
    """target 파일 Edit/Write/MultiEdit + 그 외 상태 변화 후보."""
    target_hits = []
    other_state = []
    for ln, name, tid, inp_str, inp_obj in tool_uses:
        if name in ("Edit", "Write", "MultiEdit"):
            fp = inp_obj.get("file_path") or inp_obj.get("path") or ""
            base = Path(fp).name if fp else ""
            entry = (ln, name, base, inp_str)
            if target_basename and base == target_basename:
                target_hits.append(entry)
            else:
                other_state.append(entry)
        elif name == "Bash":
            cmd = inp_obj.get("command", "") or ""
            cmd_low = cmd.lower()
            if any(kw in cmd_low for kw in ("git add", "git commit", "git checkout",
                                            "git reset", "git rm", "git mv",
                                            "rm ", "mv ", "> ", ">> ",
                                            "touch ", "sed -i", "cp ")):
                other_state.append((ln, "Bash", "", _mask(cmd)[:80]))
    return target_hits, other_state


def _load_trace(path: Path):
    from clew.ingest.claude_code import ingest_claude_code_jsonl
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return ingest_claude_code_jsonl(path)


def _cascade_waste_pairs(trace, embedder):
    """현재 코드로 waste 로 판정되는 (origin, cand) 쌍만 반환."""
    from clew.detect.structural import find_candidates
    from clew.detect.cascade import cascade
    res = cascade(trace, embedder, N, PHI)
    waste_ids = set(res.waste_span_ids)
    pairs = []
    for o, c in find_candidates(trace, N):
        if c.span_id in waste_ids:
            pairs.append((o, c))
    return pairs


def _cosine(embedder, a: str, b: str) -> float:
    from clew.detect.semantic import cosine
    return cosine(embedder.embed(a), embedder.embed(b))


# ─── 세션 하나 상세 (A~E) ────────────────────────────────────────────────
def dump_session_detail(session_file: str, embedder, do_special_E: bool = False):
    path = PROJECTS_ROOT / CUSTOS_SLUG / session_file
    trace = _load_trace(path)
    entries = _load_entries(path)
    pairs = _cascade_waste_pairs(trace, embedder)

    print("=" * 78)
    print(f"session: {session_file}   waste={len(pairs)}")
    print("=" * 78)

    for i, (o, c) in enumerate(pairs, 1):
        print(f"\n=== waste #{i} ===")
        # A
        print("--- A. 기본 ---")
        print(f"  agent_or_node_id : {c.agent_or_node_id}")
        print(f"  origin.input[:120] : {_mask(o.input_text)[:120]!r}")
        print(f"  cand.input[:120]   : {_mask(c.input_text)[:120]!r}")
        tgt = _target_basename(c)
        print(f"  target basename  : {tgt!r}")
        oh = _sha256(o.output_text)
        ch = _sha256(c.output_text)
        print(f"  sha256_equal     : {oh == ch}  (o={oh[:12]}... c={ch[:12]}...)")
        print(f"  o_len / c_len    : {len(o.output_text)} / {len(c.output_text)}  (bytes utf8: "
              f"{len(o.output_text.encode('utf-8'))} / {len(c.output_text.encode('utf-8'))})")
        try:
            cos = _cosine(embedder, o.output_text, c.output_text)
            print(f"  cosine (참고)     : {cos:.6f}  (φ={PHI}, 참고용 · 게이트는 sha256)")
        except Exception as e:
            print(f"  cosine (참고)     : <error: {e}>")
        gap = (c.start_time - o.start_time).total_seconds()
        print(f"  gap              : {gap:.1f}s  ({gap/60:.1f}min)")
        print(f"  origin.ts (KST)  : {_fmt_ts_kst(o.start_time)}")
        print(f"  cand.ts   (KST)  : {_fmt_ts_kst(c.start_time)}")

        # 라인 위치
        o_use = _find_lines_for_span(entries, o.span_id)
        c_use = _find_lines_for_span(entries, c.span_id)
        if not o_use or not c_use:
            print("  (라인 위치 미확인)")
            continue
        o_ln = o_use[0]
        c_ln = c_use[0]
        window = _window_lines(entries, o_ln, c_ln)
        print(f"  window lines     : ({o_ln}, {c_ln})  gap_lines={c_ln - o_ln}, entries in window={len(window)}")

        # B
        print("\n--- B. 창문 안 상태 변화 ---")
        vc = _window_type_value_counts(window)
        print(f"  창문 type value_counts: {vc}")
        tuses = _window_tool_uses(window)
        print(f"  창문 tool_use 수 : {len(tuses)}")
        if tuses:
            print("  (순서대로) idx | line | name | input[:80]")
            for k, (ln, name, tid, inp_str, _) in enumerate(tuses, 1):
                print(f"    {k:>3} | L{ln:<5} | {name:<12} | {inp_str}")
        target_hits, other_state = _state_change_hits(tuses, tgt)
        print(f"\n  [target={tgt!r}] Edit/Write/MultiEdit 건수: {len(target_hits)}"
              f"  (edits_in_window 재확인: 0 이어야 함)")
        for ln, name, base, inp_str in target_hits:
            print(f"    L{ln} {name} target={base!r} inp={inp_str}")
        print(f"  [기타 상태 변화 후보] Edit/Write(다른 파일) + state-changing Bash: {len(other_state)}")
        for ln, name, base, inp_str in other_state:
            print(f"    L{ln} {name} base={base!r} inp[:80]={inp_str}")

        # C
        print("\n--- C. /compact 흔적 ---")
        compact = _window_compact_markers(window)
        if compact:
            for ln, typ, key, snip in compact:
                print(f"  L{ln} type={typ!r} key={key} val[:120]={snip!r}")
        else:
            print("  창문 안 compact/summary 마커 없음")

        # D
        print("\n--- D. user 턴 ---")
        prev = _prev_user_turn(entries, c_ln)
        print("  [cand 직전 user 턴 (isCompactSummary 제외)]:")
        if prev:
            ln, txt = prev
            print(f"    L{ln} text[:300]={_mask(txt)[:300]!r}")
        else:
            print("    없음")
        wut = _window_user_turns(window)
        print(f"  [창문 안 user 턴]: {len(wut)}")
        for ln, txt in wut[:20]:
            print(f"    L{ln} text[:200]={_mask(txt)[:200]!r}")
        if len(wut) > 20:
            print(f"    ... (+{len(wut)-20} more)")

        # E (72015129 전용)
        if do_special_E:
            print("\n--- E. system-reminder / output 앞 200자 비교 ---")
            print(f"  origin.out[:200] repr: {o.output_text[:200]!r}")
            print(f"  cand.out[:200]   repr: {c.output_text[:200]!r}")
            print(f"  head_200_equal        : {o.output_text[:200] == c.output_text[:200]}")
            print(f"  full_equal (chars)    : {o.output_text == c.output_text}")
            print(f"  system-reminder in head: origin={'<system-reminder>' in o.output_text[:200]}"
                  f"  cand={'<system-reminder>' in c.output_text[:200]}")


# ─── F. 07f97584 요약표 ───────────────────────────────────────────────────
def dump_self_summary(embedder):
    path = PROJECTS_ROOT / CUSTOS_SLUG / SELF_SESSION
    trace = _load_trace(path)
    entries = _load_entries(path)
    pairs = _cascade_waste_pairs(trace, embedder)

    print("\n")
    print("=" * 78)
    print(f"Step F. 07f97584 자기 세션 요약표 (waste={len(pairs)})")
    print("=" * 78)
    hdr = f"  {'#':>3}  {'target basename':<24}  {'gap(s)':>10}  {'edits':>5}  {'user_in_window':>15}  {'agent':<12}"
    print(hdr)
    print(f"  {'-'*3}  {'-'*24}  {'-'*10}  {'-'*5}  {'-'*15}  {'-'*12}")
    for i, (o, c) in enumerate(pairs, 1):
        tgt = _target_basename(c) or "(None)"
        gap = (c.start_time - o.start_time).total_seconds()
        # edits_in_window (target)
        o_use = _find_lines_for_span(entries, o.span_id)
        c_use = _find_lines_for_span(entries, c.span_id)
        edits = "?"
        user_in = "?"
        if o_use and c_use:
            window = _window_lines(entries, o_use[0], c_use[0])
            tuses = _window_tool_uses(window)
            target_hits, _ = _state_change_hits(tuses, tgt if tgt != "(None)" else None)
            edits = str(len(target_hits))
            wut = _window_user_turns(window)
            user_in = "Y" if len(wut) > 0 else "N"
            user_in = f"{user_in}({len(wut)})"
        short_tgt = tgt if len(tgt) <= 24 else tgt[:21] + "..."
        print(f"  {i:>3}  {short_tgt:<24}  {gap:>10.1f}  {edits:>5}  {user_in:>15}  {c.agent_or_node_id:<12}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default=None,
                    help="특정 세션 prefix만 실행 (예: 2502fe9a)")
    ap.add_argument("--skip-self", action="store_true", help="F 표 생략")
    args = ap.parse_args()

    from clew.detect.semantic import Embedder
    embedder = Embedder(model_name=MODEL, revision=REV, cache_dir=CACHE_DIR)

    for fn in TARGET_SESSIONS:
        if args.only and not fn.startswith(args.only):
            continue
        do_E = fn.startswith("72015129")
        dump_session_detail(fn, embedder, do_special_E=do_E)

    if not args.skip_self and not args.only:
        dump_self_summary(embedder)


if __name__ == "__main__":
    main()
