"""드라이런: self-loop 제거 확인 + 게이트 거절 증명 (API 호출 없음)."""
import sys, os, datetime
from pathlib import Path

# API 키 없어도 graph 객체 생성 가능하도록 더미 설정
os.environ.setdefault("ANTHROPIC_API_KEY", "dummy-for-graph-inspection-only")

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from field_test.real_app import (
    make_requery_clean_app,
    make_requery_known_app,
    _REQUERY_CLEAN_QUERIES,
    fake_search,
)
from clew.detect.structural import find_repeat_candidates, _normalize_input
from clew.model import Span, Trace

print("=" * 60)
print("STAGE 1: Graph edge structure (self-loop 확인)")
print("=" * 60)

for name, factory in [("requery_clean", make_requery_clean_app),
                       ("requery_known", make_requery_known_app)]:
    app = factory()
    g = app.get_graph()
    edges = [(e.source, e.target) for e in g.edges]
    self_loops = [(s, t) for s, t in edges if s == t]
    print(f"\n[{name}] edges:")
    for src, tgt in edges:
        marker = " ← SELF-LOOP (BUG)" if src == tgt else ""
        print(f"  {src} → {tgt}{marker}")
    if self_loops:
        print(f"  !! self-loop 발견: {self_loops}")
    else:
        print(f"  OK: searcher→searcher self-loop 없음")

print()
print("=" * 60)
print("STAGE 2: Gate rejection proof (게이트 거절 증명)")
print("=" * 60)

def _make_fake_search_spans(queries: list[str]) -> Trace:
    """fake_search를 직접 호출해 tool 스팬 2개짜리 Trace 수동 구성.

    Trace 모델은 루트 스팬 정확히 1개를 요구하므로 searcher(chain) 루트 스팬을
    부모로 두고 fake_search tool 스팬 2개를 자식으로 구성한다.
    루트 자체는 반복 없이 1회만 등장 → 게이트 시험 대상은 tool 자식 스팬만.
    """
    root_output = fake_search.invoke(queries[0])  # 루트 출력은 임의값 (게이트 무관)
    root = Span(
        trace_id="diag-dry-run",
        span_id="root-0000",
        parent_span_id=None,
        agent_or_node_id="searcher",
        span_kind="chain",
        start_time="2026-06-16T00:00:00.000000Z",
        end_time="2026-06-16T00:00:00.100000Z",
        input_text=queries[0],
        output_text=root_output,
        token_count=None,
        model=None,
        cost_rate=None,
    )
    children = []
    for i, q in enumerate(queries):
        output = fake_search.invoke(q)
        children.append(Span(
            trace_id="diag-dry-run",
            span_id=f"span-{i:04d}",
            parent_span_id="root-0000",
            agent_or_node_id="fake_search",
            span_kind="tool",
            start_time=f"2026-06-16T00:00:0{i}.010000Z",
            end_time=f"2026-06-16T00:00:0{i}.020000Z",
            input_text=q,
            output_text=output,
            token_count=None,
            model=None,
            cost_rate=None,
        ))
    return Trace(trace_id="diag-dry-run", spans=[root] + children)

for label, queries in [
    ("requery_clean (다른 입력 → 후보 0 기대)", _REQUERY_CLEAN_QUERIES),
    ("requery_known (같은 입력 → 후보 1 기대)", ["quantum computing basics", "quantum computing basics"]),
]:
    trace = _make_fake_search_spans(queries)
    pairs = find_repeat_candidates(trace, n=2)

    print(f"\n[{label}]")
    print(f"  tool 스팬 수: {len(trace.spans)}")
    for s in trace.spans:
        print(f"    span={s.span_id}  kind={s.span_kind}  input={s.input_text!r}")

    print(f"  _normalize_input 비교 (tool 스팬끼리):")
    tool_spans = [s for s in trace.spans if s.span_kind == "tool"]
    a, b = tool_spans[0], tool_spans[1]
    na = _normalize_input(a.input_text)
    nb = _normalize_input(b.input_text)
    print(f"    A: {na!r}")
    print(f"    B: {nb!r}")
    same = na == nb
    print(f"    게이트 판정: {'같음 → 후보 등록' if same else '다름 → 거절'}")

    print(f"  find_repeat_candidates 결과: 후보 {len(pairs)}개")
    if pairs:
        for o, c in pairs:
            print(f"    ({o.span_id}, {c.span_id})")
    expected = 0 if "clean" in label else 1
    status = "PASS" if len(pairs) == expected else "FAIL"
    print(f"  기대={expected}  실제={len(pairs)}  → {status}")
