"""field_test/diagnostics/scan_all_cc_sessions.py

전 CC 세션 (~/.claude/projects/**/*.jsonl) 전수 스캔.
§22.10 게이트 적용 상태로 참양성 존재 여부 측정.

규율:
- 코드/정의/게이트 무수정. φ/N/model frozen. 측정만.
- transcript 커밋 금지. path basename 마스킹. 코드 앞 80자 절단.
- 결론 금지. raw 만. 판단은 세션 소유자.
- §21.4 조용히 skip 금지 — 파싱 실패 파일명 + 에러 명시.

Usage:
    python field_test/diagnostics/scan_all_cc_sessions.py
"""
from __future__ import annotations

import hashlib
import json
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


def _target_basename(span) -> str | None:
    try:
        inp = json.loads(span.input_text)
    except Exception:
        return None
    fp = inp.get("file_path") or inp.get("path") or ""
    return Path(fp).name if fp else None


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


def _fmt_ts_utc_kst(dt) -> str:
    kst = dt.astimezone(KST)
    return f"UTC={dt.isoformat()} KST={kst.isoformat()}"


def _ingest_with_warns(path: Path):
    from clew.ingest.claude_code import ingest_claude_code_jsonl
    warn_msgs: list[str] = []
    err: str | None = None
    trace = None
    with warnings.catch_warnings(record=True) as ws:
        warnings.simplefilter("always")
        try:
            trace = ingest_claude_code_jsonl(path)
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
        for w in ws:
            warn_msgs.append(str(w.message))
    return trace, warn_msgs, err


def _bash_command_only_stats(trace) -> dict:
    """Bash span 을 command 텍스트만으로 그룹핑(§22.9 참고 데이터, 측정만)."""
    bash_spans = [
        s for s in sorted(trace.spans, key=lambda s: s.start_time)
        if s.agent_or_node_id == "Bash"
    ]
    groups: dict[str, list] = {}
    for s in bash_spans:
        try:
            inp = json.loads(s.input_text)
        except Exception:
            continue
        cmd = inp.get("command", "")
        if not cmd:
            continue
        groups.setdefault(cmd, []).append(s)
    stats = {"groups_with_repeat": 0, "repeat_pairs": 0, "sha256_equal_true": 0}
    for cmd, occ in groups.items():
        if len(occ) < 2:
            continue
        stats["groups_with_repeat"] += 1
        origin = occ[0]
        for cand in occ[1:]:
            stats["repeat_pairs"] += 1
            if _sha256(origin.output_text) == _sha256(cand.output_text):
                stats["sha256_equal_true"] += 1
    return stats


def main() -> None:
    from clew.detect.structural import find_candidates
    from clew.detect.cascade import cascade
    from clew.detect.semantic import Embedder

    t0 = time.perf_counter()

    sessions = sorted(PROJECTS_ROOT.glob("*/*.jsonl"))

    # --- Step 1 ---
    print("=" * 78)
    print(f"Step 1. 전 세션 목록 (root={PROJECTS_ROOT})")
    print("=" * 78)
    print(f"총 jsonl 파일: {len(sessions)}")

    embedder = Embedder(model_name=MODEL, revision=REV, cache_dir=CACHE_DIR)

    per_session = []
    parse_errors: list[tuple[str, str]] = []
    for p in sessions:
        trace, warn_msgs, err = _ingest_with_warns(p)
        if err is not None:
            parse_errors.append((p.name, err))
            per_session.append({
                "path": p, "name": p.name, "slug": p.parent.name,
                "spans": 0, "cands": [], "waste_ids": [],
                "warn_count": len(warn_msgs), "warn_msgs": warn_msgs,
                "err": err, "trace": None, "bash": None,
            })
            continue
        cands = find_candidates(trace, N)
        res = cascade(trace, embedder, N, PHI)
        bash_stats = _bash_command_only_stats(trace)
        per_session.append({
            "path": p, "name": p.name, "slug": p.parent.name,
            "spans": len(trace.spans),
            "cands": cands,
            "waste_ids": list(res.waste_span_ids),
            "warn_count": len(warn_msgs),
            "warn_msgs": warn_msgs,
            "err": None, "trace": trace, "bash": bash_stats,
        })

    print(f"파싱 실패: {len(parse_errors)} 건")
    for name, err in parse_errors:
        print(f"  {name}: {err}")
    if not parse_errors:
        print("  (없음)")
    # 파싱 경고 있는 파일 (§21.4 조용히 skip 금지 위해 명시)
    files_with_warns = [(r["name"], r["warn_count"]) for r in per_session if r["warn_count"] > 0]
    print(f"\n파싱 경고 있는 파일: {len(files_with_warns)} / {len(sessions)}")
    for name, wc in files_with_warns:
        print(f"  {name}: {wc} 건")
    if files_with_warns:
        print("\n경고 종류 (unique message):")
        uniq = set()
        for r in per_session:
            for m in r["warn_msgs"]:
                uniq.add(m[:140])
        for m in sorted(uniq):
            print(f"  - {m!r}")

    # --- Step 2 ---
    print()
    print("=" * 78)
    print("Step 2. 전수 clew analyze 요약 (φ=0.514345, N=2, sha256 게이트 ON)")
    print("=" * 78)
    hdr = f"  {'#':>3}  {'session (uuid8..last8)':<24} {'slug (앞40)':<42} {'spans':>6} {'cands':>6} {'waste':>6} {'warn':>5}"
    print(hdr)
    print(f"  {'-'*3}  {'-'*24} {'-'*42} {'-'*6} {'-'*6} {'-'*6} {'-'*5}")
    tot_spans = 0
    tot_cands = 0
    tot_waste = 0
    for i, r in enumerate(per_session, 1):
        nm = r["name"]
        # uuid는 앞 8 + "..." + 확장자 앞 8
        stem = nm.rsplit(".", 1)[0]
        if len(stem) > 20:
            short = stem[:8] + ".." + stem[-8:]
        else:
            short = stem
        slug_short = r["slug"][:40]
        print(f"  {i:>3}  {short:<24} {slug_short:<42} {r['spans']:>6} "
              f"{len(r['cands']):>6} {len(r['waste_ids']):>6} {r['warn_count']:>5}")
        tot_spans += r["spans"]
        tot_cands += len(r["cands"])
        tot_waste += len(r["waste_ids"])
    print(f"  {'-'*3}  {'-'*24} {'-'*42} {'-'*6} {'-'*6} {'-'*6} {'-'*5}")
    print(f"  합계                                                                 "
          f"{tot_spans:>6} {tot_cands:>6} {tot_waste:>6}")

    # --- Step 3 ---
    print()
    print("=" * 78)
    print("Step 3. waste > 0 세션 상세")
    print("=" * 78)
    hit_sessions = [r for r in per_session if len(r["waste_ids"]) > 0]
    if not hit_sessions:
        print("  waste > 0 인 세션 없음 (참양성 이 라운드에서 관측 안 됨)")
    else:
        for r in hit_sessions:
            print(f"\n--- session: {r['name']}  (slug={r['slug']}, waste={len(r['waste_ids'])}) ---")
            trace = r["trace"]
            for idx, (o, c) in enumerate(r["cands"], 1):
                if c.span_id not in r["waste_ids"]:
                    continue
                oh = _sha256(o.output_text)
                ch = _sha256(c.output_text)
                tgt = _target_basename(c)
                edits = _edits_between(trace, o.start_time, c.start_time, tgt)
                gap_sec = (c.start_time - o.start_time).total_seconds()
                print(f"  waste #{idx}:")
                print(f"    agent_or_node_id : {c.agent_or_node_id}")
                print(f"    input(target basename) : {tgt!r}")
                print(f"    sha256_equal    : {oh == ch}")
                print(f"      origin.output sha256 : {oh}")
                print(f"      cand.output   sha256 : {ch}")
                print(f"    output len(chars) : o={len(o.output_text)}  c={len(c.output_text)}")
                print(f"    edits_in_window(target) : {edits}")
                print(f"    gap             : {gap_sec:.1f}s")
                print(f"    origin.ts       : {_fmt_ts_utc_kst(o.start_time)}")
                print(f"    cand.ts         : {_fmt_ts_utc_kst(c.start_time)}")
                print(f"    origin.out[:150]: {o.output_text[:150]!r}")
                print(f"    cand.out[:150]  : {c.output_text[:150]!r}")

    # --- Step 4 ---
    print()
    print("=" * 78)
    print("Step 4. sha256 게이트 통계 (전 세션 repeat 후보 전체)")
    print("=" * 78)
    total_cands = 0
    equal_true = 0
    equal_false = 0
    true_no_edit = 0
    true_with_edit = 0
    # 강한 참양성 후보 리스트 (True + edits_in_window==0) 개별 나열
    strong_hits: list[tuple[str, str, str, int, int]] = []  # (session, agent, target, o_len, c_len)
    anomaly_hits: list[tuple[str, str, str, int]] = []  # (session, agent, target, edits)
    for r in per_session:
        if r["trace"] is None:
            continue
        trace = r["trace"]
        for (o, c) in r["cands"]:
            total_cands += 1
            oh = _sha256(o.output_text)
            ch = _sha256(c.output_text)
            equal = (oh == ch)
            tgt = _target_basename(c)
            edits = _edits_between(trace, o.start_time, c.start_time, tgt)
            if equal:
                equal_true += 1
                if edits == 0:
                    true_no_edit += 1
                    strong_hits.append((r["name"], c.agent_or_node_id, str(tgt),
                                        len(o.output_text), len(c.output_text)))
                else:
                    true_with_edit += 1
                    anomaly_hits.append((r["name"], c.agent_or_node_id, str(tgt), edits))
            else:
                equal_false += 1
    print(f"  총 repeat 후보 (전 세션 합): {total_cands}")
    print(f"    sha256_equal True         : {equal_true}")
    print(f"    sha256_equal False        : {equal_false}")
    print(f"    True 이면서 edits_in_window==0 (강한 참양성 후보): {true_no_edit}")
    print(f"    True 이면서 edits_in_window >0 (이상 케이스)  : {true_with_edit}")
    if strong_hits:
        print("\n  [강한 참양성 후보 목록]")
        for s, name, tgt, ol, cl in strong_hits:
            print(f"    - {s} | {name} | target={tgt!r} | o_len={ol} c_len={cl}")
    if anomaly_hits:
        print("\n  [이상 케이스 목록 — 편집 있는데 output 동일]")
        for s, name, tgt, ed in anomaly_hits:
            print(f"    - {s} | {name} | target={tgt!r} | edits={ed}")

    # --- Step 5 ---
    print()
    print("=" * 78)
    print("Step 5. Bash command-only 재조회 (참고, §22.9 측정만)")
    print("=" * 78)
    bt_groups = 0
    bt_pairs = 0
    bt_sha_true = 0
    per_session_bash = []
    for r in per_session:
        if r["bash"] is None:
            continue
        bt_groups += r["bash"]["groups_with_repeat"]
        bt_pairs += r["bash"]["repeat_pairs"]
        bt_sha_true += r["bash"]["sha256_equal_true"]
        if r["bash"]["repeat_pairs"] > 0:
            per_session_bash.append((r["name"], r["bash"]))
    print(f"  Bash command 재조회 그룹 (2회 이상): {bt_groups}")
    print(f"  Bash 재조회 쌍 수 (origin→cand)     : {bt_pairs}")
    print(f"  그중 sha256_equal True (output 동일): {bt_sha_true}")
    print(f"  주: 현재 게이트는 input 전체(description 포함) 서명 기준이므로 이들은")
    print(f"      cascade waste 후보로 안 뜬다. §22.9 사전등록 근거 데이터 (측정만).")
    if per_session_bash:
        print("\n  [세션별 Bash 재조회 통계]")
        for name, bs in per_session_bash:
            print(f"    - {name}: groups={bs['groups_with_repeat']} "
                  f"pairs={bs['repeat_pairs']} sha_true={bs['sha256_equal_true']}")

    elapsed = time.perf_counter() - t0
    print()
    print("=" * 78)
    print(f"wall time: {elapsed:.1f}s")
    print("=" * 78)


if __name__ == "__main__":
    main()
