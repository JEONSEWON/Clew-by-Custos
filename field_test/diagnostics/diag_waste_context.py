"""field_test/diagnostics/diag_waste_context.py

§22.8.8 waste 4건 판정 재료 재구성 진단 스크립트 (커밋 금지 대상 아님 — 도구 자체는 커밋).

규율:
- transcript 자체는 레포에 커밋 금지 (~/.claude/projects/ 에서 읽기만).
- 경로는 basename 마스킹. tool input 요약은 앞 80자 절단.
- 결론 쓰지 않는다. raw 만 뽑는다.

대상: `f96aee88-df87-41a6-8f6e-be05d3928018.jsonl` (§22.6/§22.7/§22.8.8 동일 세션).
waste 4건 (§22.8.8):
  #1 origin=toolu_01FpniGnXxoE4AXg1R5SodkT cand=toolu_01JRtN5gD5Kasqx6s5uZ7eZA
  #2 origin=toolu_01FpniGnXxoE4AXg1R5SodkT cand=toolu_019vePnaQrtbXGzKLNvF7pUn
  #3 origin=toolu_016ruLyijuJSr2qDxWRagJen cand=toolu_01FyRBDgmMtoMk83jhGPbfpY
  #4 origin=toolu_017bFHLqnQgAawh1jtWVMy3g cand=toolu_01YSSm43o4VmMzA17sX8Cqqb

Usage:
    python field_test/diagnostics/diag_waste_context.py --n 1     # waste #1
    python field_test/diagnostics/diag_waste_context.py --n 2     # waste #2
    python field_test/diagnostics/diag_waste_context.py --n 3     # waste #3 (+ F. sha256)
    python field_test/diagnostics/diag_waste_context.py --n 4     # waste #4
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

TARGET_JSONL = (
    Path.home()
    / ".claude/projects/C--Users-User-Desktop-Custos---clwe-project"
    / "f96aee88-df87-41a6-8f6e-be05d3928018.jsonl"
)

KST = timezone(timedelta(hours=9))

WASTE = {
    "1": ("toolu_01FpniGnXxoE4AXg1R5SodkT", "toolu_01JRtN5gD5Kasqx6s5uZ7eZA"),
    "2": ("toolu_01FpniGnXxoE4AXg1R5SodkT", "toolu_019vePnaQrtbXGzKLNvF7pUn"),
    "3": ("toolu_016ruLyijuJSr2qDxWRagJen", "toolu_01FyRBDgmMtoMk83jhGPbfpY"),
    "4": ("toolu_017bFHLqnQgAawh1jtWVMy3g", "toolu_01YSSm43o4VmMzA17sX8Cqqb"),
}

TARGET_FILE_BASENAME = {
    "1": "run_swechat_waste_scan.py",
    "2": "run_swechat_waste_scan.py",
    "3": "SWECHAT_SPEC.md",
    "4": None,  # #4 는 Bash. 아래 D 판정에서 별도 처리.
}


def _mask(txt: str) -> str:
    if not isinstance(txt, str):
        return str(txt)
    txt = re.sub(r"[A-Za-z]:[\\/][^\"\\\s]+[\\/]([^\\/\"]+)", r"BASENAME(\1)", txt)
    txt = re.sub(r"(?:/[^/\"\s]+)+/([^/\"]+)", r"BASENAME(\1)", txt)
    return txt


def _load_entries():
    entries = []
    with TARGET_JSONL.open(encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            s = line.strip()
            if not s:
                continue
            entries.append((lineno, json.loads(s)))
    return entries


def _parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _find_span_lines(entries, span_id: str):
    """(use_lineno, use_ts, use_input, result_lineno, result_ts) 반환."""
    use = None
    res = None
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
            if block.get("type") == "tool_result" and block.get("tool_use_id") == span_id:
                res = (lineno, d.get("timestamp"), block)
    return use, res


def _window(entries, use_lineno_o, res_lineno_c):
    """origin.tool_use line 이후 ~ cand.tool_use line 이전까지 (배타적) 반환.
    실무적으로 origin 의 tool_result 이후~cand 의 tool_use 이전이 '창문'이나,
    엄격 판정을 위해 origin.tool_use lineno < x < cand.tool_use lineno 로 잡는다."""
    return [(ln, d) for ln, d in entries if use_lineno_o < ln < res_lineno_c]


def _extract_tool_uses(window):
    out = []
    for ln, d in window:
        if d.get("type") != "assistant":
            continue
        msg = d.get("message")
        if not isinstance(msg, dict):
            continue
        for block in msg.get("content", []):
            if isinstance(block, dict) and block.get("type") == "tool_use":
                inp = block.get("input", {})
                s = _mask(json.dumps(inp, ensure_ascii=False))[:80]
                out.append((ln, block.get("name"), block.get("id"), s, inp))
    return out


def _find_compact_markers(window):
    hits = []
    for ln, d in window:
        if d.get("compactMetadata") is not None:
            meta = d.get("compactMetadata")
            hits.append((ln, "compactMetadata", d.get("type"), str(meta)[:120]))
        if d.get("isCompactSummary") is True:
            hits.append((ln, "isCompactSummary", d.get("type"), "True"))
    return hits


def _extract_user_texts(window):
    out = []
    for ln, d in window:
        if d.get("type") != "user":
            continue
        # skip compact-summary user turns (별도 C 에서 표시)
        if d.get("isCompactSummary") is True:
            continue
        msg = d.get("message")
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        if isinstance(content, str):
            out.append((ln, content))
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    out.append((ln, block.get("text", "")))
                elif isinstance(block, dict) and block.get("type") == "tool_result":
                    # tool_result 은 F 관련이 아니면 여기 안 뽑음
                    pass
    return out


def _extract_assistant_texts(window):
    out = []
    for ln, d in window:
        if d.get("type") != "assistant":
            continue
        msg = d.get("message")
        if not isinstance(msg, dict):
            continue
        for block in msg.get("content", []):
            if isinstance(block, dict) and block.get("type") == "text":
                out.append((ln, block.get("text", "")))
    return out


def _get_output_text_for_result(entries, span_id: str) -> str | None:
    for ln, d in entries:
        msg = d.get("message")
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_result" and block.get("tool_use_id") == span_id:
                c = block.get("content")
                if isinstance(c, str):
                    return c
                if isinstance(c, list):
                    parts = []
                    for b in c:
                        if isinstance(b, dict) and b.get("type") == "text":
                            parts.append(b.get("text", ""))
                        else:
                            parts.append(json.dumps(b, sort_keys=True, ensure_ascii=False))
                    return "\n".join(parts)
    return None


def _fmt_ts_utc_kst(ts: str) -> str:
    dt = _parse_ts(ts)
    kst = dt.astimezone(KST)
    return f"UTC={dt.isoformat()} KST={kst.isoformat()}"


def diag(n: str):
    entries = _load_entries()
    origin_id, cand_id = WASTE[n]
    o_use, o_res = _find_span_lines(entries, origin_id)
    c_use, c_res = _find_span_lines(entries, cand_id)
    if o_use is None or c_use is None:
        print(f"span not found: origin={origin_id} cand={cand_id}")
        return

    print(f"===== waste #{n} =====")
    print(f"origin.tool_use.id = {origin_id}")
    print(f"cand.tool_use.id   = {cand_id}")

    # A. 창문 정보
    print("\n--- A. 창문 정보 ---")
    o_ts = o_use[1]
    c_ts = c_use[1]
    o_ln = o_use[0]
    c_ln = c_use[0]
    o_dt = _parse_ts(o_ts)
    c_dt = _parse_ts(c_ts)
    elapsed = c_dt - o_dt
    print(f"origin.line = {o_ln}   cand.line = {c_ln}   gap_lines = {c_ln - o_ln}")
    print(f"origin.ts : {_fmt_ts_utc_kst(o_ts)}")
    print(f"cand.ts   : {_fmt_ts_utc_kst(c_ts)}")
    print(f"elapsed   : {elapsed} (={elapsed.total_seconds():.1f}s)")

    # 창문
    window = _window(entries, o_ln, c_ln)

    # B. 창문 안 tool_use
    print("\n--- B. 창문 안 tool_use (순서대로) ---")
    tuses = _extract_tool_uses(window)
    print(f"count = {len(tuses)}")
    for ln, name, tid, inp_str, inp_obj in tuses:
        print(f"  line={ln:>4} {name:<12} input[:80]={inp_str}")

    # target 파일 Edit/Write/MultiEdit 검사
    tf = TARGET_FILE_BASENAME[n]
    print(f"\n[B-check] target 파일 Edit/Write/MultiEdit (basename={tf!r}):")
    hits = []
    if tf is not None:
        for ln, name, tid, inp_str, inp_obj in tuses:
            if name in ("Edit", "Write", "MultiEdit"):
                fp = inp_obj.get("file_path") or inp_obj.get("path") or ""
                if Path(fp).name == tf:
                    hits.append((ln, name, fp, inp_obj))
    if hits:
        for ln, name, fp, inp_obj in hits:
            print(f"  line={ln:>4} {name} on {tf}")
            # 어떤 편집인지 요약 (앞 80자)
            for k in ("old_string", "new_string", "content"):
                v = inp_obj.get(k)
                if v is not None:
                    print(f"    {k}[:80]={_mask(str(v))[:80]!r}")
    else:
        print(f"  없음 (target 파일에 대한 Edit/Write/MultiEdit 0건)")

    # #4 는 파일 변경 가능한 Bash 도 검사
    if n == "4":
        print("\n[B-check #4] 상태 변화 가능성 있는 Bash / Edit / Write / MultiEdit / git 계열:")
        state_change = []
        for ln, name, tid, inp_str, inp_obj in tuses:
            if name in ("Edit", "Write", "MultiEdit"):
                state_change.append((ln, name, inp_str))
            elif name == "Bash":
                cmd = inp_obj.get("command", "")
                cmd_low = cmd.lower()
                if any(kw in cmd_low for kw in ("git add", "git commit", "git checkout", "git reset", "git rm", "git mv", "rm ", "mv ", "> ", ">> ", "touch ", "sed -i", "cp ")):
                    state_change.append((ln, "Bash", _mask(cmd)[:80]))
        if state_change:
            for ln, name, s in state_change:
                print(f"  line={ln:>4} {name}: {s!r}")
        else:
            print("  없음 (창문 안 상태 변화 가능성 있는 tool_use 0건)")

    # C. compact 마커
    print("\n--- C. /compact 흔적 ---")
    print("(전체 파일 raw 확인 결과: type=system + compactMetadata / type=user + isCompactSummary=True)")
    ch = _find_compact_markers(window)
    if ch:
        for ln, key, typ, snip in ch:
            print(f"  line={ln:>4} type={typ!r} key={key!r} val[:120]={snip!r}")
    else:
        print("  창문 안 없음")

    # D. user 턴
    print("\n--- D. user 턴 (cand 직전 user + 창문 안 user) ---")
    # cand 직전 user (line 이 cand_ln 보다 작은 것 중 최대)
    prev_user = None
    for ln, d in entries:
        if ln >= c_ln:
            break
        if d.get("type") == "user" and d.get("isCompactSummary") is not True:
            msg = d.get("message")
            if not isinstance(msg, dict):
                continue
            content = msg.get("content")
            text = None
            if isinstance(content, str):
                text = content
            elif isinstance(content, list):
                for b in content:
                    if isinstance(b, dict) and b.get("type") == "text":
                        text = b.get("text", "")
                        break
                    if isinstance(b, dict) and b.get("type") == "tool_result":
                        continue
            if text:
                prev_user = (ln, text)
    print(f"[cand 직전 user 턴 (isCompactSummary 제외)]")
    if prev_user:
        ln, txt = prev_user
        print(f"  line={ln}  text[:300]={_mask(txt)[:300]!r}")
    else:
        print("  없음")

    print(f"\n[창문 안 user 턴 (isCompactSummary 제외)]")
    ut = _extract_user_texts(window)
    if ut:
        for ln, txt in ut:
            print(f"  line={ln}  text[:200]={_mask(txt)[:200]!r}")
    else:
        print("  없음")

    # E. assistant text
    print("\n--- E. 창문 안 assistant text 블록 ---")
    at = _extract_assistant_texts(window)
    if at:
        for ln, txt in at[:20]:
            snippet = _mask(txt)[:200]
            print(f"  line={ln}  text[:200]={snippet!r}")
        if len(at) > 20:
            print(f"  ... (+{len(at) - 20} more)")
        print(f"  total assistant text blocks in window: {len(at)}")
    else:
        print("  없음")

    # F. #3 전용: output 바이트 동일성
    if n == "3":
        print("\n--- F. output_text 바이트 동일성 (#3 전용) ---")
        o_out = _get_output_text_for_result(entries, origin_id)
        c_out = _get_output_text_for_result(entries, cand_id)
        if o_out is None or c_out is None:
            print(f"  origin.output_text or cand.output_text is None")
        else:
            o_bytes = o_out.encode("utf-8")
            c_bytes = c_out.encode("utf-8")
            o_sha = hashlib.sha256(o_bytes).hexdigest()
            c_sha = hashlib.sha256(c_bytes).hexdigest()
            print(f"  origin.output_text len (chars/bytes) = {len(o_out)}/{len(o_bytes)}")
            print(f"  cand.output_text   len (chars/bytes) = {len(c_out)}/{len(c_bytes)}")
            print(f"  origin sha256 = {o_sha}")
            print(f"  cand   sha256 = {c_sha}")
            print(f"  bytes_equal   = {o_bytes == c_bytes}")
            print(f"  chars_equal   = {o_out == c_out}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", required=True, choices=list(WASTE.keys()))
    args = ap.parse_args()
    if not TARGET_JSONL.exists():
        raise SystemExit(f"target session not found: {TARGET_JSONL}")
    diag(args.n)


if __name__ == "__main__":
    main()
