"""requery_clean FAIL 원인 진단 (read-only, 수정 없음)."""
import sys, json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from clew.io import load_trace
from clew.detect.structural import find_repeat_candidates, _normalize_input

TRACE_PATH = Path(__file__).parent / "real_requery_clean.json"

# ── 1. 로드 ──────────────────────────────────────────────────────────────────
trace = load_trace(TRACE_PATH)
print(f"=== 트레이스 로드: {len(trace.spans)} 스팬 ===\n")

# ── 2. 스팬 목록 (시간순) ─────────────────────────────────────────────────────
from clew.detect.structural import _spans_by_start_time
ordered = _spans_by_start_time(trace)

print(f"{'span_id':<20} {'agent_or_node_id':<20} {'span_kind':<8} {'parent_id':<20} input[:60]  |  output[:60]")
print("-" * 130)
for s in ordered:
    inp = (s.input_text or "")[:60].replace("\n", " ")
    out = (s.output_text or "")[:60].replace("\n", " ")
    print(f"{s.span_id:<20} {s.agent_or_node_id:<20} {s.span_kind:<8} {str(s.parent_span_id):<20} {inp!r}  |  {out!r}")

# ── fake_search / searcher 집계 ───────────────────────────────────────────────
print()
for name in ("fake_search", "searcher"):
    spans = [s for s in ordered if s.agent_or_node_id == name]
    print(f"[{name}] 총 {len(spans)}개")
    for s in spans:
        print(f"  span_id={s.span_id}  kind={s.span_kind}  input={repr((s.input_text or '')[:80])}")

# ── 3. find_repeat_candidates 결과 ───────────────────────────────────────────
print("\n=== find_repeat_candidates(n=2) ===")
pairs = find_repeat_candidates(trace, n=2)
print(f"후보 쌍 수: {len(pairs)}")
for origin, cand in pairs:
    o_norm = _normalize_input(origin.input_text or "")
    c_norm = _normalize_input(cand.input_text or "")
    same = o_norm == c_norm
    print(f"\n  origin : {origin.span_id}  kind={origin.span_kind}  node={origin.agent_or_node_id}")
    print(f"    input_norm = {o_norm[:80]!r}")
    print(f"  cand   : {cand.span_id}  kind={cand.span_kind}  node={cand.agent_or_node_id}")
    print(f"    input_norm = {c_norm[:80]!r}")
    print(f"  게이트 판정: {'같음(후보)' if same else '다름(필터돼야 함)'}")
    print(f"  is_tool(origin): {origin.span_kind == 'tool'}")
    print(f"  → 실제로 후보에 포함됨: YES  (←  이 쌍이 FIRE 원인)")

# ── 4. 스팬 32929bcd40f49540 분석 ────────────────────────────────────────────
TARGET = "32929bcd40f49540"
print(f"\n=== 낭비 판정된 스팬 {TARGET} ===")
t = next((s for s in trace.spans if s.span_id == TARGET), None)
if t:
    print(f"  node={t.agent_or_node_id}  kind={t.span_kind}  parent={t.parent_span_id}")
    print(f"  input={repr((t.input_text or '')[:120])}")
    in_pair = [(o, c) for o, c in pairs if c.span_id == TARGET or o.span_id == TARGET]
    for o, c in in_pair:
        role = "cand(낭비)" if c.span_id == TARGET else "origin"
        print(f"  쌍 역할: {role}  ←→  {o.span_id if c.span_id == TARGET else c.span_id}")

# ── 결론 ─────────────────────────────────────────────────────────────────────
print("""
=== 결론 ===
(C) tool이 아닌 kind=chain 노드(searcher)에서 후보가 생성됨.
    searcher는 span_kind='chain'이므로 find_repeat_candidates의
    is_tool=False → 입력 게이트(input_text 비교)가 적용되지 않음.
    두 searcher 스팬의 input_text는 실제로 다르지만(loop_count·result 필드 상이)
    게이트를 통과하지 않으므로 무조건 쌍으로 등록된다.
    fake_search(tool) 쌍은 gate가 올바르게 막음("basics" ≠ "advances").
    → FIRE 원인: searcher(chain) 반복 스팬이 게이트 없이 후보로 잡힘.
""")
